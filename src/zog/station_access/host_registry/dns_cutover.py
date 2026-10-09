"""Review, freeze, adopt, activate: forward-only migration under one controller lock."""
import json
import re
import uuid
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from zog.network_register.adoption import RecordAdoption
from zog.network_register.contracts import NetworkError
from zog.network_register.engine import DnsEngine, matches
from zog.network_register.evidence import EvidenceGate
from zog.network_register.ledger import OperationLedger, digest
from zog.network_register.models import RecordSnapshot, canonical
from zog.network_register.state import save
from zog.network_register.store import SqliteStateStore
from .dns_evidence import selection, RegistryEvidenceSource, RegistrySecretResolver
from .models import DnsAssignment


def legacy_binding(config):
    return dict(schema=1,domain=config['domain'],suffix=config['suffix'],account_id=config['account_id'])


def controller_state(config):
    root=Path(config['state_directory'])
    value=json.loads((root/'controller.json').read_text())
    if value==legacy_binding(config):return dict(writer='legacy')
    if (not isinstance(value,dict) or value.get('schema')!=2 or value.get('binding')!=legacy_binding(config)
            or value.get('writer') not in ('frozen','shared','paused')
            or not isinstance(value.get('review_id'),str) or not re.fullmatch('[0-9a-f]{64}',value['review_id'])
            or value.get('stage') not in ('frozen','initializing','importing','adopted','active')):
        raise NetworkError('storage')
    if (value['writer'] in ('shared','paused')) != (value['stage']=='active'):raise NetworkError('storage')
    return value


def load_review(root, review_id):
    if not isinstance(review_id,str) or not re.fullmatch('[0-9a-f]{64}',review_id):raise NetworkError('validation')
    review=json.loads((root/('dns-review-'+review_id+'.json')).read_text())
    if digest(review)!=review_id:raise NetworkError('storage')
    return review


class Authorization:
    def __init__(self, source):self.source=source
    def authorize(self, actor, owner_id, connection, binding, action):
        self.source.current()
        s=self.source.selected
        return (actor==owner_id==s.connection.owner_id and connection==s.connection
                and (binding is None or all(getattr(binding,k)==getattr(s.binding,k) for k in ('id','owner_id','connection_id','zone_id','zone_name','prefix','nameservers'))))


def runtime(data, *, store=None, collector=None, provider_factory=None, allow_empty=False):
    selected=selection(data,allow_empty=allow_empty)
    if collector is None:
        from zog.network_register.dns_authority import DnsAuthorityCollector
        collector=DnsAuthorityCollector()
    source=RegistryEvidenceSource(selected,collector)
    gate=EvidenceGate(source)
    evidence=gate.authority(selected.connection,selected.binding)
    class Cached:
        def authority(self,*_):return evidence  # immutable timestamps, checked on every use
    source.collector=Cached()
    ledger=OperationLedger(store,Authorization(source)) if store else SimpleNamespace(store=None)
    engine=DnsEngine(ledger,gate,RegistrySecretResolver(source),provider_factory=provider_factory)
    return selected,source,engine


def local_snapshot(config, selected):
    c,b=selected.connection,selected.binding
    if (c.provider,c.account_ref,b.zone_name,b.prefix)!=('cloudflare',config['account_id'],config['domain'],config['suffix']):
        raise NetworkError('unsupported')
    root=Path(config['state_directory'])/'network-register'
    rows=list(DnsAssignment.objects.order_by('name'))
    if set(str(r.host_id) for r in rows)!=set(selected.host_ids):raise NetworkError('conflict')
    files={p.name for p in root.glob('assignment-*.json')}
    if files!={'assignment-'+canonical(r.name)+'.json' for r in rows}:raise NetworkError('conflict')
    result=[]
    for row in rows:
        name=canonical(row.name)
        if not name.endswith('.'+b.prefix) or '.' in name[:-(len(b.prefix)+1)]:raise NetworkError('conflict')
        legacy=json.loads((root/('assignment-'+name+'.json')).read_text())
        if (legacy.get('schema'),legacy.get('account_id'),legacy.get('domain'),legacy.get('zone_id'),legacy.get('name'),legacy.get('owner_id'))!=(
                1,c.account_ref,b.zone_name,b.zone_id,row.name,row.owner_id):raise NetworkError('conflict')
        if legacy.get('phase') not in ('present','absent') or row.record_id!=(legacy.get('record_id') or ''):
            raise NetworkError('conflict')
        marker='Zog network-register owner '+__import__('hashlib').sha256(json.dumps([c.account_ref,b.zone_id,row.name,row.owner_id]).encode()).hexdigest()
        if legacy['phase']=='present':
            record=legacy['record']
            snapshot=RecordSnapshot(record['name'],record['content'],record['ttl'],record['type'],record['proxied'])
            if not matches(record,snapshot,marker,legacy['record_id']):raise NetworkError('conflict')
            if not matches(dict(legacy['desired'],id=legacy['record_id']),snapshot,marker,legacy['record_id']):
                raise NetworkError('conflict')
        else:
            if legacy.get('record_id') is not None or legacy.get('record') is not None or legacy.get('desired') is not None:
                raise NetworkError('conflict')
            snapshot=None;marker=None
        item=dict(resource_id=str(row.host_id),name=row.name,record_id=legacy.get('record_id'),
                  snapshot=asdict(snapshot) if snapshot else None,marker=marker,desired_revision=row.revision)
        result.append(dict(item=item,enabled=row.enabled,desired_action=row.desired_action,
                           desired_address=row.desired_address,applied_revision=row.applied_revision,
                           legacy_hash=digest(legacy),legacy_owner=row.owner_id))
    return result


def validate_records(engine, selected, snapshots):
    c,b=selected.connection,selected.binding
    rows=engine._inventory(engine.provider_factory(c),c,b,selected.host_ids[0])
    for entry in snapshots:
        item=entry['item'];relevant=engine._relevant(rows,item['name'],b.zone_name)
        if item['snapshot'] is None:
            if relevant:raise NetworkError('conflict')
        elif len(relevant)!=1 or not matches(relevant[0],RecordSnapshot(**item['snapshot']),item['marker'],item['record_id']):
            raise NetworkError('conflict')
    engine._gate(c,b,selected.host_ids[0],None,'inspect')


def review(config, data, *, collector=None, provider_factory=None):
    from .dns_reconcile import controller_lock
    with controller_lock(config,modes=('legacy',)) as root:
        selected,source,engine=runtime(data,collector=collector,provider_factory=provider_factory)
        before=local_snapshot(config,selected)
        validate_records(engine,selected,before)
        if local_snapshot(config,selected)!=before:raise NetworkError('conflict')
        value=dict(schema=1,nonce=str(uuid.uuid4()),selection=data,legacy=before,
                   connection=asdict(selected.connection),binding=asdict(selected.binding))
        review_id=digest(value)
        save(root/('dns-review-'+review_id+'.json'),value)
        return dict(review_id=review_id,writer='legacy',records=before,provider_writes=0,
                    next_ttl=300,scope=dict(zone=selected.binding.zone_name,prefix=selected.binding.prefix))


def commit(config, review_id, *, collector=None, provider_factory=None):
    """Explicitly approved review; retry the SAME ID to resume, never auto rollback."""
    from .dns_reconcile import controller_lock
    with controller_lock(config,modes=('legacy','frozen','shared')) as root:
        state=controller_state(config)
        reviewed=load_review(root,review_id)
        from .dns_evidence import owner_authorized
        owner_authorized(reviewed['selection']['owner_user_id'])
        if state['writer']!='legacy' and state['review_id']!=review_id:raise NetworkError('conflict')
        if state['writer']=='shared':
            store=SqliteStateStore(root/('dns-ledger-'+review_id+'.sqlite3'))
            with store.transaction():
                if store.read('meta','cutover')!=dict(review_id=review_id) or not store.read('adoption',digest([reviewed['connection']['owner_id'],review_id])):
                    raise NetworkError('storage')
            return dict(writer='shared',review_id=review_id,provider_writes=0)
        selected,source,probe=runtime(reviewed['selection'],collector=collector,provider_factory=provider_factory)
        if digest(asdict(selected.connection))!=digest(reviewed['connection']) or digest(asdict(selected.binding))!=digest(reviewed['binding']):
            raise NetworkError('conflict')
        if local_snapshot(config,selected)!=reviewed['legacy']:raise NetworkError('conflict')
        validate_records(probe,selected,reviewed['legacy'])
        if state['writer']=='legacy':
            state=dict(schema=2,binding=legacy_binding(config),writer='frozen',review_id=review_id,stage='frozen')
            save(root/'controller.json',state)  # fail closed before any new ledger work
        path=root/('dns-ledger-'+review_id+'.sqlite3')
        if state['stage']=='frozen':
            state['stage']='initializing';save(root/'controller.json',state)
            store=SqliteStateStore(path,create=True)
        else:store=SqliteStateStore(path)  # missing/lost state is never recreated
        with store.transaction():
            meta=store.read('meta','cutover')
            if meta is None:
                if state['stage']!='initializing' or any(store.all(k) for k in ('connection','binding','operation','record','reservation','adoption')):
                    raise NetworkError('storage')
                store.write('connection',selected.connection.id,asdict(selected.connection))
                store.write('binding',selected.binding.id,asdict(selected.binding))
                store.write('meta','cutover',dict(review_id=review_id))
            elif meta!=dict(review_id=review_id):raise NetworkError('storage')
        state['stage']='importing';save(root/'controller.json',state)
        ledger=OperationLedger(store,Authorization(source))
        engine=DnsEngine(ledger,probe.gate,RegistrySecretResolver(source),provider_factory=provider_factory)
        RecordAdoption(engine).adopt(selected.connection.owner_id,selected.connection.owner_id,selected.binding.id,
            review_id,[e['item'] for e in reviewed['legacy']],connection_revision=selected.connection.revision,
            binding_revision=selected.binding.revision)
        state['stage']='adopted';save(root/'controller.json',state)
        # Recheck exact provider IDs/content and unchanged legacy intent before switch.
        validate_records(engine,selected,reviewed['legacy'])
        source.current()
        if local_snapshot(config,selected)!=reviewed['legacy']:raise NetworkError('conflict')
        with store.transaction():
            receipt=store.read('adoption',digest([selected.connection.owner_id,review_id]))
            if not receipt or len(receipt['records'])!=len(reviewed['legacy']):raise NetworkError('storage')
            for record in receipt['records']:
                expected={'deleted':True} if record.get('deleted') else {k:v for k,v in record.items() if k!='name'}
                if store.read('record',record['id'])!=expected:raise NetworkError('storage')
        state.update(writer='shared',stage='active');save(root/'controller.json',state)
        return dict(writer='shared',review_id=review_id,provider_writes=0)


def pause(config):
    from .dns_reconcile import controller_lock
    with controller_lock(config,modes=('shared','paused')) as root:
        state=controller_state(config)
        from .dns_evidence import owner_authorized
        owner_authorized(load_review(root,state['review_id'])['selection']['owner_user_id'])
        state['writer']='paused';save(root/'controller.json',state)
        return dict(writer='paused',review_id=state['review_id'])


def resume(config, *, collector=None, provider_factory=None):
    from .dns_reconcile import controller_lock
    with controller_lock(config,modes=('paused',)) as root:
        state=controller_state(config);reviewed=load_review(root,state['review_id'])
        store=SqliteStateStore(root/('dns-ledger-'+state['review_id']+'.sqlite3'))
        selected,source,engine=runtime(reviewed['selection'],store=store,collector=collector,provider_factory=provider_factory)
        with store.transaction():
            if store.read('meta','cutover')!=dict(review_id=state['review_id']):raise NetworkError('storage')
        source.current();state['writer']='shared';save(root/'controller.json',state)
        return dict(writer='shared',review_id=state['review_id'])
