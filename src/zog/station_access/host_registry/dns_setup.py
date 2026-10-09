"""Reviewed additional DNS destination installation. Provider operations are reads only."""
import re,time,uuid
from dataclasses import asdict
from types import SimpleNamespace
from zog.network_register.contracts import NetworkError
from zog.network_register.models import Connection,canonical,below
from zog.network_register.cloudflare import CloudflareDns
from zog.network_register.porkbun_dns import PorkbunDns
from zog.network_register.dns_authority import DnsAuthorityCollector
from zog.network_register.evidence import EvidenceGate
from zog.network_register.ledger import digest
from zog.network_register.state import save
from zog.network_register.store import SqliteStateStore
from .dns_evidence import owner_authorized,selection,RegistryEvidenceSource,RegistrySecretResolver
from .dns_reconcile import controller_lock
from .dns_cutover import load_review
from .models import ProviderCredential,DnsDestination,SecurityAudit
from .identity import locked

PORKBUN_NS=['curitiba.ns.porkbun.com','fortaleza.ns.porkbun.com','maceio.ns.porkbun.com','salvador.ns.porkbun.com']
MESSAGES={
 'credentials':'Check the saved API credentials and their current revision.',
 'domain-access':'Check domain API access, account ownership, provider permissions and active nameserver configuration.',
 'nameservers':'The provider did not supply a supported nameserver configuration.',
 'authority':'Check parent delegation, authoritative SOA availability and conflicting delegation or aliases at the prefix.',
 'records':'The provider record inventory could not be read completely. Check permissions or retry after a provider outage.',
 'namespace':'This prefix overlaps an existing destination or provider records. Choose another prefix; existing owned records require operator-reviewed import.',
 'review':'The review expired or its inputs changed. Review the destination again.',
 'controller':'Initialize or resume the shared DNS controller before adding destinations.',
 'storage':'Destination state is unavailable. Preserve the ledger and ask an operator to inspect it.',
}
class Blocked(Exception):
 def __init__(self,stage,code='conflict'):
  self.stage,self.code=stage,code
 def report(self):
  message=MESSAGES[self.stage]
  if self.code=='authentication':message='Provider authentication failed. Replace or correct the saved API credentials.'
  elif self.code=='rate-limit':message='The provider rate limit was reached. Wait before checking again.'
  elif self.code=='transient':message='The provider or DNS service is temporarily unavailable. Retry the read-only check later.'
  return dict(stage=self.stage,code=self.code,message=message,ready=False)

def source_for(owner,credential_id,revision):
 owner_authorized(owner)
 row=ProviderCredential.objects.get(pk=credential_id)
 if type(revision) is not int or row.revision!=revision:raise Blocked('credentials')
 cid='provider:'+str(row.pk)
 c=Connection(cid,'user:'+str(owner),row.provider,row.account_id or cid,cid+':'+str(revision),revision,'ready')
 return RegistryEvidenceSource(SimpleNamespace(connection=c,owner_user_id=owner),None)

def provider(source,factory=None):
 c=source.selected.connection
 return factory(c) if factory else (CloudflareDns if c.provider=='cloudflare' else PorkbunDns)(c,RegistrySecretResolver(source))

def zones(owner,credential_id,revision,cursor=None,*,provider_factory=None):
 try:
  source=source_for(owner,credential_id,revision);page=provider(source,provider_factory).list_zones(cursor);source.current()
  return dict(zones=[dict(id=r['id'],name=canonical(r['name'])) for r in page.items],cursor=page.next_cursor,credential_revision=revision)
 except NetworkError as e:raise Blocked('domain-access',e.code) from None

def scope_available(config,prefix,exclude=None):
 prefixes=[config['suffix']]+[x['prefix'] for x in DnsDestination.objects.exclude(pk=exclude).values_list('selection',flat=True)]
 if any(p==prefix or below(p,prefix) or below(prefix,p) for p in prefixes):raise Blocked('namespace')

def candidate(owner,credential_id,revision,zone_id,label,*,binding_id=None,provider_factory=None):
 if not isinstance(label,str) or not re.fullmatch('[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label):raise Blocked('namespace','validation')
 source=source_for(owner,credential_id,revision)
 try:zone=provider(source,provider_factory).get_zone(zone_id)
 except NetworkError as e:raise Blocked('domain-access',e.code) from None
 c=source.selected.connection
 if zone.get('id')!=zone_id or zone.get('account',{}).get('id')!=c.account_ref or zone.get('status')!='active':raise Blocked('domain-access')
 name=canonical(zone['name']);ns=PORKBUN_NS if c.provider=='porkbun' else zone.get('name_servers')
 if not isinstance(ns,(list,tuple)) or not ns:raise Blocked('nameservers')
 data=dict(schema=1,owner_user_id=owner,credential_id=str(credential_id),credential_revision=revision,
  binding_id=binding_id or 'destination-'+uuid.uuid4().hex,binding_revision=1,zone_id=zone_id,zone_name=name,
  prefix=label+'.'+name,nameservers=sorted(canonical(n) for n in ns),host_ids=[])
 selection(data,allow_empty=True);source.current()
 return data

def validate(data,*,collector=None,provider_factory=None,empty=True):
 selected=selection(data,allow_empty=True);c,b=selected.connection,selected.binding
 source=RegistryEvidenceSource(selected,collector or DnsAuthorityCollector())
 try:
  api=provider(source,provider_factory);zone=api.get_zone(b.zone_id)
  if zone.get('id')!=b.zone_id or canonical(zone.get('name'))!=b.zone_name or zone.get('account',{}).get('id')!=c.account_ref or zone.get('status')!='active':raise NetworkError('conflict')
 except NetworkError as e:raise Blocked('domain-access',e.code) from None
 try:evidence=EvidenceGate(source).authority(c,b)
 except NetworkError as e:raise Blocked('authority',e.code) from None
 try:
  cursor=None;seen=set();ids=set()
  for _ in range(1000):
   page=api.list_records(b.zone_id,cursor)
   for row in page.items:
    if not row.get('id') or row['id'] in ids:raise NetworkError('validation')
    ids.add(row['id']);name=row['name']
    if empty and (name==b.prefix or below(name,b.prefix) or ((row['type'] in ('CNAME','DNAME') or (row['type']=='NS' and name!=b.zone_name)) and below(b.prefix,name))):raise Blocked('namespace')
   if page.next_cursor is None:break
   if page.next_cursor in seen:raise NetworkError('validation')
   seen.add(page.next_cursor);cursor=page.next_cursor
  else:raise NetworkError('validation')
 except NetworkError as e:raise Blocked('records',e.code) from None
 source.current()
 class Cached:
  def authority(self,*_):return evidence
 source.collector=Cached()
 try:EvidenceGate(source).authority(c,b)
 except NetworkError as e:raise Blocked('authority',e.code) from None
 return selected

def review(config,owner,credential_id,revision,zone_id,label,**kw):
 if not config:raise Blocked('controller')
 with controller_lock(config,modes=('shared',)) as root:
  data=candidate(owner,credential_id,revision,zone_id,label,provider_factory=kw.get('provider_factory'))
  scope_available(config,data['prefix']);validate(data,**kw)
  value=dict(kind='destination-setup',selection=data,expires_at=time.time()+600)
  rid=digest(value);save(root/('dns-review-'+rid+'.json'),value)
  return dict(review_id=rid,expires_at=value['expires_at'],domain=data['zone_name'],prefix=data['prefix'],nameservers=data['nameservers'],provider=selection(data,allow_empty=True).connection.provider,provider_writes=0,write_permission='unverified',ready=True)

def commit(config,owner,review_id,**kw):
 if not config:raise Blocked('controller')
 with controller_lock(config,modes=('shared',)) as root:
  value=load_review(root,review_id)
  if value.get('kind')!='destination-setup' or value['selection']['owner_user_id']!=owner:raise Blocked('review','permission')
  data=value['selection'];selected=selection(data,allow_empty=True);owner_authorized(owner)
  existing=DnsDestination.objects.filter(pk=data['binding_id']).first()
  relative='destination-'+review_id+'.sqlite3';path=root/relative
  if existing:
   if existing.selection!=data or existing.ledger_path!=relative or not existing.enabled or not path.is_file():raise Blocked('storage')
   store=SqliteStateStore(path)
   with store.transaction():
    if (store.read('meta','destination-setup')!=dict(review_id=review_id) or digest(store.read('connection',selected.connection.id))!=digest(asdict(selected.connection)) or digest(store.read('binding',selected.binding.id))!=digest(asdict(selected.binding))):raise Blocked('storage')
   return dict(binding_id=existing.pk,provider_writes=0,replayed=True)
  if time.time()>value['expires_at']:raise Blocked('review')
  scope_available(config,data['prefix'])
  current=candidate(owner,data['credential_id'],data['credential_revision'],data['zone_id'],data['prefix'][:-(len(data['zone_name'])+1)],binding_id=data['binding_id'],provider_factory=kw.get('provider_factory'))
  if current!=data:raise Blocked('review')
  validate(data,**kw)
  # Atomic ledger initialization precedes DB publication. A retry of this review
  # can consume its exact orphan ledger after a crash, but never reset an active ledger.
  store=SqliteStateStore(path,create=not path.exists())
  with store.transaction():
   c,b=selected.connection,selected.binding
   if store.read('connection',c.id):
    if store.read('meta','destination-setup')!=dict(review_id=review_id) or digest(store.read('connection',c.id))!=digest(asdict(c)) or digest(store.read('binding',b.id))!=digest(asdict(b)):raise Blocked('storage')
   else:
    if any(store.all(k) for k in ('connection','binding','operation','record')):raise Blocked('storage')
    store.write('connection',c.id,asdict(c));store.write('binding',b.id,asdict(b));store.write('meta','destination-setup',dict(review_id=review_id))
  with locked():
   selection(data,allow_empty=True);scope_available(config,data['prefix'])
   DnsDestination.objects.create(id=b.id,selection=data,ledger_path=relative,enabled=True)
   SecurityAudit.objects.create(actor=c.owner_id,action='dns-destination-setup',details=dict(binding_id=b.id,review_id=review_id,prefix=b.prefix))
  return dict(binding_id=b.id,provider_writes=0,replayed=False)

def inspect(config,owner,binding_id,**kw):
 """Explicit read-only inspection; does not reconcile, recover or change intent."""
 from .dns_shared import open_runtime
 from .dns_destinations import runtime
 from .models import Host
 from zog.network_register.evidence import fresh
 from zog.network_register.ledger import TERMINAL
 if not config:raise Blocked('controller')
 owner_authorized(owner)
 with controller_lock(config,modes=('shared',)) as root:
  if binding_id=='primary':
   from .dns_cutover import controller_state
   data=load_review(root,controller_state(config)['review_id'])['selection']
  else:
   destination=DnsDestination.objects.get(pk=binding_id);data=destination.selection
  if data['owner_user_id']!=owner:raise Blocked('credentials','permission')
  try:selection(data,allow_empty=True)
  except NetworkError as e:raise Blocked('credentials',e.code) from None
  validate(data,empty=False,**kw)
  try:selected,source,engine=open_runtime(config,root,**kw) if binding_id=='primary' else runtime(destination,root,**kw)
  except NetworkError as e:raise Blocked('storage',e.code) from None
  with engine.store.transaction():pending=[o for o in engine.store.all('operation') if o['state'] not in TERMINAL]
  c,b=selected.connection,selected.binding;hosts=[]
  for resource in selected.host_ids:
   h=Host.objects.get(pk=resource)
   try:
    evidence=source.host(c.owner_id,b.id,resource)
    engine.gate.check(c,b,resource,evidence.desired,'publish' if evidence.publish_enabled else 'unpublish',evidence.desired_revision)
   except NetworkError as e:
    stale=not h.signed_dns_observed_at or not fresh(h.signed_dns_observed_at.timestamp(),time.time()) or not h.aws_checked_at or not fresh(h.aws_checked_at.timestamp(),time.time())
    hosts.append(dict(host_id=resource,stage='host-evidence',code='stale-evidence' if stale else e.code,message='Wait for a fresh signed beacon and AWS inventory scan.' if stale else 'Check approved identity, running AWS state, matching addresses and desired intent.'));continue
   if pending:
    hosts.append(dict(host_id=resource,stage='recovery',code='pending-operation',message='The retained operation awaits reconciliation or explicit recovery; this check does not retry writes.'));continue
   try:
    plan=engine.plan(c.owner_id,c.owner_id,b.id,resource,evidence.desired,evidence.desired_revision,delete=evidence.desired is None)
    hosts.append(dict(host_id=resource,stage='records',code='change-pending' if plan else 'synchronized',message='A change is awaiting reconciliation.' if plan else 'Owned provider record matches saved intent.'))
   except NetworkError as e:
    hosts.append(dict(host_id=resource,stage='records',code=e.code,message='Provider state does not match verified ownership or could not be read. Inspect the assignment before retrying.'))
  labels={str(h.pk):h.label for h in Host.objects.filter(pk__in=selected.host_ids)}
  for item in hosts:item['label']=labels.get(item['host_id']) or item['host_id']
  return dict(ready=not pending and all(h['code']=='synchronized' for h in hosts),mode='read-only',authority='verified',provider_reads='verified',write_permission='unverified',
   operations=[dict(state=o['state'],host_id=o['plan']['resource_id'],code=o.get('last_error_code')) for o in pending],hosts=hosts,provider_writes=0)
