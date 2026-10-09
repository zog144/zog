"""Shared-engine worker. Caller holds controller.lock for the whole evaluation."""
from dataclasses import asdict
from django.utils import timezone
from zog.network_register.contracts import NetworkError
from zog.network_register.ledger import TERMINAL, digest
from zog.network_register.store import SqliteStateStore
from .dns_cutover import controller_state, load_review, runtime
from .dns_evidence import RegistryEvidenceSource
from .identity import locked
from .models import DnsAssignment


def open_runtime(config, root, *, collector=None, provider_factory=None, pending_review=None):
    state=controller_state(config)
    if state['writer'] not in ('shared','paused'):raise NetworkError('permission')
    reviewed=load_review(root,state['review_id'])
    store=SqliteStateStore(root/('dns-ledger-'+state['review_id']+'.sqlite3'))
    with store.transaction():
        if store.read('meta','cutover')!=dict(review_id=state['review_id']):raise NetworkError('storage')
    from .dns_membership import membership
    members=membership(store,reviewed)
    if members['pending'] and members['pending']!=pending_review:raise NetworkError('conflict')
    data=dict(reviewed['selection'],host_ids=members['host_ids'])
    return runtime(data,store=store,collector=collector,provider_factory=provider_factory,allow_empty=True)


def refresh_intent(source, gate, resource):
    """Verify observed intent before saving it; no remote I/O under the DB lock.

    runtime() has already cached DNS observations with their original timestamps.
    Security-sensitive host updates and intent changes share the security lock.
    """
    from zog.network_register.evidence import EvidenceGate
    proposed=RegistryEvidenceSource(source.selected,source.collector,use_observed_address=True)
    proposed_gate=EvidenceGate(proposed)
    c,b=source.selected.connection,source.selected.binding
    with locked():
        evidence=proposed.host(c.owner_id,b.id,resource)
        action='publish' if evidence.publish_enabled else 'unpublish'
        proposed_gate.check(c,b,resource,evidence.desired,action,evidence.desired_revision)
        row=DnsAssignment.objects.get(host_id=resource)
        wanted=('present',evidence.desired.address) if evidence.desired else ('absent','')
        if (row.desired_action,row.desired_address)!=wanted:
            row.desired_action,row.desired_address=wanted;row.revision+=1
            row.save(update_fields=['desired_action','desired_address','revision'])
        return row,evidence.desired


def project(resource, status, *, operation=None, record=None, revision=None):
    values=dict(status=status,last_attempt=timezone.now(),error='',error_code='')
    if operation:
        values.update(last_action=operation['state'],error_code=operation.get('last_error_code') or '')
        if operation['state']=='succeeded':
            values.update(last_action=operation['plan']['action'],last_change=timezone.now())
    if status in ('synchronized','unpublished'):
        values.update(last_success=timezone.now(),applied_revision=revision,
                      record_id=record['record_id'] if record else '',
                      observed_address=record['last_applied']['address'] if record else '')
    DnsAssignment.objects.filter(host_id=resource).update(**values)


def reconcile_locked(config, root, *, collector=None, provider_factory=None, resource_ids=None):
    if controller_state(config)['writer']!='shared':raise NetworkError('permission')
    selected,source,engine=open_runtime(config,root,collector=collector,provider_factory=provider_factory)
    return reconcile_runtime(selected,source,engine,resource_ids=resource_ids)


def reconcile_runtime(selected,source,engine, *, resource_ids=None, refresh=refresh_intent, projection=project):
    """Evaluate one destination; caller serializes all membership and writes."""
    c,b=selected.connection,selected.binding;actor=c.owner_id
    from zog.network_register.models import resource_uuid
    targets=selected.host_ids if resource_ids is None else tuple(resource_uuid(v) for v in resource_ids)
    if not targets and resource_ids is None:return {}
    if not targets or len(set(targets))!=len(targets) or not set(targets)<=set(selected.host_ids):raise NetworkError('permission')
    with engine.store.transaction():
        pending=[o for o in engine.store.all('operation') if o['binding_id']==b.id and o['state'] not in TERMINAL]
    if len(pending)>1:raise NetworkError('storage')
    if pending:
        op=pending[0];resource=op['plan']['resource_id']
        if resource not in targets:return {'pending_other_host':1}
        if op['state'] in ('uncertain','conflict'):
            projection(resource,op['state'],operation=op);return {op['state']:1}
        if op['state']=='prepared':
            try:row,desired=refresh(source,engine.gate,resource)
            except NetworkError:
                projection(resource,'waiting_verification');return {'waiting':1}
            if op['plan']['desired_revision']!=row.revision or op['plan']['after']!=(asdict(desired) if desired else None):
                op=engine.ledger.transition(actor,c.owner_id,op['request_id'],op['revision'],'cancelled')
        if op['state'] not in TERMINAL:
            op=engine.apply(actor,c.owner_id,op['request_id'],op['revision'])
            if op['state'] not in TERMINAL:
                projection(resource,op['state'],operation=op);return {op['state']:1}
            if op['state']=='failed':projection(resource,'failed',operation=op);return {'failed':1}
            if op['state']=='succeeded':
                _,_,record=engine.ledger.context(actor,c.owner_id,b.id,resource)
                projection(resource,'synchronized' if record else 'unpublished',operation=op,record=record,revision=op['plan']['desired_revision'])
    outcomes={}
    for resource in targets:
        try:
            row,desired=refresh(source,engine.gate,resource)
            plan=engine.plan(actor,c.owner_id,b.id,resource,desired,row.revision,delete=desired is None)
            op=None
            if plan is not None:
                request='dns:'+digest(plan.to_dict())
                op=engine.ledger.prepare(actor,request,plan)
                op=engine.apply(actor,c.owner_id,request,op['revision'])
                if op['state']!='succeeded':
                    projection(resource,op['state'],operation=op)
                    outcomes[op['state']]=outcomes.get(op['state'],0)+1
                    return outcomes  # never leap over an unresolved binding operation
            _,_,record=engine.ledger.context(actor,c.owner_id,b.id,resource)
            status='synchronized' if desired else 'unpublished'
            projection(resource,status,operation=op,record=record,revision=row.revision)
            outcomes[status]=outcomes.get(status,0)+1
        except NetworkError as error:
            status='conflict' if error.code=='conflict' else 'waiting_verification'
            projection(resource,status);outcomes[status]=outcomes.get(status,0)+1
            return outcomes
    return outcomes


def status(config):
    """Local evidence only; no DNS queries or provider/credential access."""
    from .dns_reconcile import controller_lock
    from .dns_evidence import owner_authorized
    with controller_lock(config,modes=('legacy','frozen','shared','paused')) as root:
        state=controller_state(config)
        if state['writer']=='legacy':return state
        reviewed=load_review(root,state['review_id']);owner_authorized(reviewed['selection']['owner_user_id'])
        result=dict(state,records=[e['item'] for e in reviewed['legacy']],operations=[])
        if state['stage'] in ('importing','adopted','active'):
            store=SqliteStateStore(root/('dns-ledger-'+state['review_id']+'.sqlite3'))
            from .dns_membership import membership
            result['membership']=membership(store,reviewed)
            with store.transaction():
                result['operations']=store.all('operation')
                result['membership_operations']=store.all('membership-operation')
                result['name_receipts']=store.all('name-receipt')
                result['current_records']=store.all('record')
        return result
