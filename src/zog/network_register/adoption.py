"""Explicit, atomic adoption of reviewed legacy/Zog records; provider reads only."""
from dataclasses import asdict
from .contracts import NetworkError
from .engine import matches
from .ledger import digest, TERMINAL
from .models import ManagedRecord, RecordSnapshot, resource_uuid, identifier, revision, below


class RecordAdoption:
    def __init__(self, engine):
        self.engine,self.ledger,self.store=engine,engine.ledger,engine.store

    def adopt(self, actor, owner_id, binding_id, request_id, items, *, connection_revision, binding_revision):
        identifier(request_id);revision(connection_revision);revision(binding_revision)
        if not isinstance(items,(list,tuple)) or not 1<=len(items)<=256:raise NetworkError('validation')
        checked=[]
        for item in items:
            if set(item)!={'resource_id','record_id','snapshot','marker','desired_revision','name'}:raise NetworkError('validation')
            r=resource_uuid(item['resource_id']);revision(item['desired_revision'])
            from .models import canonical
            name=canonical(item['name'])
            if item['snapshot'] is None:
                if item['record_id'] is not None or item['marker'] is not None:raise NetworkError('validation')
                checked.append(dict(id=digest([binding_id,r]),resource_id=r,name=name,deleted=True))
                continue
            identifier(item['record_id'])
            snapshot=RecordSnapshot(**item['snapshot'])
            if snapshot.name!=name:raise NetworkError('validation')
            # Validate the provenance marker without changing it on the provider.
            managed=ManagedRecord(digest([binding_id,r]),owner_id,binding_id,r,item['record_id'],snapshot,
                                  item['desired_revision'],self.ledger._now(),item['marker'])
            if not managed.marker:raise NetworkError('validation')
            checked.append(dict(asdict(managed),name=name))
        if len({r['resource_id'] for r in checked})!=len(checked) or len({r['record_id'] for r in checked if not r.get('deleted')})!=sum(not r.get('deleted',False) for r in checked):
            raise NetworkError('conflict')
        payload=digest([binding_id,connection_revision,binding_revision,items])
        key=digest([owner_id,request_id])
        with self.store.worker_lock():
            with self.store.transaction():
                c,b=self.ledger._context(binding_id)
                self.ledger._authorize(actor,owner_id,c,b,'adopt')
                old=self.store.read('adoption',key)
                if old:
                    if old['payload_hash']!=payload:raise NetworkError('conflict')
                    return old
                if c.status!='ready' or b.status!='ready' or (c.revision,b.revision)!=(connection_revision,binding_revision):
                    raise NetworkError('conflict')
                if any(o['binding_id']==b.id and o['state'] not in TERMINAL for o in self.store.all('operation')):
                    raise NetworkError('conflict')
            rows=self.engine._inventory(self.engine.provider_factory(c),c,b,checked[0]['resource_id'])
            for record in checked:
                name=record['name']
                if not below(name,b.prefix) or '.' in name[:-(len(b.prefix)+1)]:raise NetworkError('validation')
                relevant=self.engine._relevant(rows,name,b.zone_name)
                if record.get('deleted'):
                    if relevant:raise NetworkError('conflict')
                elif len(relevant)!=1 or not matches(relevant[0],RecordSnapshot(**record['last_applied']),record['marker'],record['record_id']):
                    raise NetworkError('conflict')
            self.engine._gate(c,b,checked[0]['resource_id'],None,'inspect')
            with self.store.transaction():
                current_c,current_b=self.ledger._context(binding_id)
                self.ledger._authorize(actor,owner_id,current_c,current_b,'adopt')
                if (current_c,current_b)!=(c,b):raise NetworkError('conflict')
                if any(o['binding_id']==b.id and o['state'] not in TERMINAL for o in self.store.all('operation')):
                    raise NetworkError('conflict')
                reservations=self.store.all('reservation')
                if len({r['name'] for r in checked})!=len(checked):raise NetworkError('conflict')
                for record in checked:
                    if self.store.read('record',record['id']) is not None:raise NetworkError('conflict')
                    if any(r['name']==record['name'] for r in reservations):raise NetworkError('conflict')
                for record in checked:
                    self.store.write('record',record['id'],({'deleted':True} if record.get('deleted') else {k:v for k,v in record.items() if k!='name'}))
                    self.store.write('reservation',digest(record['name']),dict(name=record['name'],
                        binding_id=b.id,resource_id=record['resource_id']))
                receipt=dict(owner_id=owner_id,request_id=request_id,binding_id=b.id,payload_hash=payload,
                             actor=actor,at=self.ledger._now(),state='adopted',records=checked)
                self.store.write('adoption',key,receipt)
                return receipt
