"""Reviewed membership changes, fenced across the ledger and Django database."""
import json
import re
import uuid
from dataclasses import asdict, replace
from types import SimpleNamespace
from zog.network_register.contracts import NetworkError
from zog.network_register.evidence import EvidenceGate
from zog.network_register.ledger import digest
from zog.network_register.models import resource_uuid, canonical
from zog.network_register.reservations import NameReservations
from zog.network_register.state import save
from .dns_cutover import controller_state, load_review
from .dns_evidence import RegistryEvidenceSource
from .dns_reconcile import controller_lock, serialize_assignment
from .identity import locked
from .models import DnsAssignment, SecurityAudit


def membership(store, reviewed):
    with store.transaction():
        value=store.read('meta','membership')
        enabled=store.read('meta','membership-enabled')
    if value is None:
        if enabled:raise NetworkError('storage')
        return dict(revision=0,host_ids=reviewed['selection']['host_ids'],pending=None)
    if (not enabled or set(value)!={'revision','host_ids','pending'} or type(value['revision']) is not int
            or value['revision']<0 or not isinstance(value['host_ids'],list)
            or len(value['host_ids'])>256 or len(set(value['host_ids']))!=len(value['host_ids'])):
        raise NetworkError('storage')
    for resource in value['host_ids']:resource_uuid(resource)
    if value['pending'] is not None and not re.fullmatch('[0-9a-f]{64}',value['pending']):raise NetworkError('storage')
    return value


def intent(resource):
    row=DnsAssignment.objects.filter(host_id=resource).first()
    if row is None:return None
    return {key:getattr(row,key) for key in ('name','owner_id','enabled','revision','desired_action','desired_address','record_id')}


def proposed(source, resource, name, floor):
    selected=replace(source.selected,host_ids=tuple(set(source.selected.host_ids)|{resource}))
    row=SimpleNamespace(name=name,enabled=True,revision=floor,desired_action='present',desired_address='')
    evidence=RegistryEvidenceSource(selected,source.collector,use_observed_address=True,proposed_assignments={resource:row})
    c,b=selected.connection,selected.binding
    host=evidence.host(c.owner_id,b.id,resource)
    EvidenceGate(evidence).check(c,b,resource,host.desired,'publish',floor)
    return asdict(host.desired)


def owner(selected, actor_id):
    if actor_id is not None and actor_id!=selected.owner_user_id:raise NetworkError('permission')


def preview(engine, resource, name, action):
    c,b=engine.ledger.context(engine.gate.source.selected.connection.owner_id,
        engine.gate.source.selected.connection.owner_id,engine.gate.source.selected.binding.id,resource)[:2]
    return NameReservations(engine).check(c.owner_id,c.owner_id,b.id,resource,name,action,
        connection_revision=c.revision,binding_revision=b.revision)


def review(config, resource, action, label=None, *, actor_id=None, **runtime_kw):
    from .dns_shared import open_runtime
    resource=resource_uuid(str(resource))
    if action not in ('reserve','release'):raise NetworkError('validation')
    with controller_lock(config,modes=('shared',)) as root:
        selected,source,engine=open_runtime(config,root,**runtime_kw);owner(selected,actor_id)
        original=load_review(root,controller_state(config)['review_id'])
        members=membership(engine.store,original)
        old=intent(resource)
        if action=='reserve':
            if old or resource in members['host_ids'] or len(members['host_ids'])>=256:raise NetworkError('conflict')
            if not isinstance(label,str) or not re.fullmatch('[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label):raise NetworkError('validation')
            name=canonical(label+'.'+selected.binding.prefix)
            if DnsAssignment.objects.filter(name=name).exists():raise NetworkError('conflict')
        else:
            if label is not None:raise NetworkError('validation')
            if resource not in members['host_ids'] or not old or old['enabled'] or old['record_id'] or old['desired_action']!='absent':
                raise NetworkError('conflict')
            name=old['name']
        checked=preview(engine,resource,name,action)
        desired=proposed(source,resource,name,checked['revision_floor']) if action=='reserve' else None
        snapshot=DnsAssignment.objects.filter(host_id=resource).first()
        value=dict(schema=1,nonce=str(uuid.uuid4()),action=action,resource_id=resource,name=name,
            membership=members,intent=old,connection=asdict(selected.connection),binding=asdict(selected.binding),
            desired=desired,revision_floor=checked['revision_floor'],
            assignment=json.loads(json.dumps(serialize_assignment(snapshot),default=str)) if snapshot else None)
        key=digest(value);save(root/('dns-membership-review-'+key+'.json'),value)
        return dict(review_id=key,**value,provider_writes=0)


def load(root, key):
    if not isinstance(key,str) or not re.fullmatch('[0-9a-f]{64}',key):raise NetworkError('validation')
    value=json.loads((root/('dns-membership-review-'+key+'.json')).read_text())
    if digest(value)!=key:raise NetworkError('storage')
    return value


def commit(config, review_id, *, actor_id=None, resource_id=None, **runtime_kw):
    from .dns_shared import open_runtime
    with controller_lock(config,modes=('shared',)) as root:
        value=load(root,review_id);resource=value['resource_id']
        if resource_id is not None and str(resource_id)!=resource:raise NetworkError('permission')
        selected,source,engine=open_runtime(config,root,pending_review=review_id,**runtime_kw);owner(selected,actor_id)
        c,b=selected.connection,selected.binding;store=engine.store
        if digest([asdict(c),asdict(b)])!=digest([value['connection'],value['binding']]):raise NetworkError('conflict')
        with store.transaction():operation=store.read('membership-operation',review_id)
        if operation and operation['phase']=='completed':return operation['result']
        if operation and operation['phase']=='cancelled':raise NetworkError('conflict')
        members=membership(store,load_review(root,controller_state(config)['review_id']))
        def verify_intent():
            if intent(resource)!=value['intent']:raise NetworkError('conflict')
            if value['action']=='reserve' and proposed(source,resource,value['name'],value['revision_floor'])!=value['desired']:
                raise NetworkError('conflict')
        if operation is None:
            if members!=value['membership']:raise NetworkError('conflict')
            verify_intent()
            if preview(engine,resource,value['name'],value['action'])['revision_floor']!=value['revision_floor']:raise NetworkError('conflict')
            with store.transaction():
                store.write('meta','membership-enabled',{'enabled':True})
                store.write('meta','membership',dict(members,pending=review_id))
                store.write('membership-operation',review_id,dict(phase='prepared',review_id=review_id,resource_id=resource))
        elif members['pending']!=review_id:raise NetworkError('storage')
        receipt=NameReservations(engine).change(c.owner_id,c.owner_id,b.id,resource,value['name'],value['action'],
            'membership:'+review_id,connection_revision=c.revision,binding_revision=b.revision)
        with locked():
            audit=SecurityAudit.objects.filter(action='dns-membership',details__review_id=review_id).first()
            if audit is None:
                verify_intent()
                if value['action']=='reserve':
                    DnsAssignment.objects.create(host_id=resource,name=value['name'],owner_id='host-discover:'+resource,
                        enabled=True,revision=receipt['revision_floor'],desired_action='present',
                        desired_address=value['desired']['address'],status='pending')
                else:DnsAssignment.objects.get(host_id=resource).delete()
                SecurityAudit.objects.create(actor=c.owner_id,action='dns-membership',host_id_text=resource,
                    details=dict(review_id=review_id,review=value,receipt=receipt))
        hosts=set(members['host_ids'])
        if value['action']=='reserve':hosts.add(resource)
        else:hosts.discard(resource)
        result=dict(review_id=review_id,resource_id=resource,action=value['action'],name=value['name'],
            membership_revision=members['revision']+1,provider_writes=0)
        with store.transaction():
            store.write('meta','membership',dict(revision=result['membership_revision'],host_ids=sorted(hosts),pending=None))
            store.write('membership-operation',review_id,dict(phase='completed',review_id=review_id,resource_id=resource,result=result))
        return result


def cancel(config, review_id, *, actor_id=None):
    """Clear a prepared fence only when neither ledger nor projection changed."""
    from zog.network_register.store import SqliteStateStore
    from .dns_evidence import owner_authorized
    with controller_lock(config,modes=('shared',)) as root:
        value=load(root,review_id);state=controller_state(config);original=load_review(root,state['review_id'])
        owner_id=original['selection']['owner_user_id'];owner_authorized(owner_id)
        if actor_id is not None and actor_id!=owner_id:raise NetworkError('permission')
        store=SqliteStateStore(root/('dns-ledger-'+state['review_id']+'.sqlite3'))
        members=membership(store,original)
        with locked(),store.transaction():
            if members['pending']!=review_id:raise NetworkError('conflict')
            if store.read('name-receipt',digest(['user:'+str(owner_id),'membership:'+review_id])) or SecurityAudit.objects.filter(action='dns-membership',details__review_id=review_id).exists():
                raise NetworkError('conflict')
            store.write('membership-operation',review_id,dict(phase='cancelled',review_id=review_id,resource_id=value['resource_id']))
            store.write('meta','membership',dict(members,pending=None))
        return dict(review_id=review_id,state='cancelled',provider_writes=0)
