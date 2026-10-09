"""Trusted evidence adapter and read-only pre-migration readiness inspection.

Selection is an administrator-owned configuration, not host/browser input.
No engine mutation, ledger provisioning, adoption, or legacy credential fallback.
"""
from dataclasses import dataclass
from datetime import datetime
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from zog.network_register.contracts import NetworkError
from zog.network_register.evidence import CloudIdentity, EvidenceGate, HostEvidence, fresh
from zog.network_register.models import Connection, ZoneBinding, RecordSnapshot, resource_uuid
from zog.network_register.lifecycle import ReadOnlyConnectionValidator
from .models import Host, HostIdentity, DnsAssignment, InventoryScan, ProviderCredential


@dataclass(frozen=True)
class Selection:
    owner_user_id: int
    connection: Connection
    binding: ZoneBinding
    host_ids: tuple[str, ...]


def owner_authorized(owner_user_id):
    if type(owner_user_id) is not int or not get_user_model().objects.filter(
            pk=owner_user_id,is_active=True,is_superuser=True).exists():
        raise NetworkError('permission')


def selection(data, *, allow_empty=False):
    fields={'schema','owner_user_id','credential_id','credential_revision','binding_id','binding_revision',
            'zone_id','zone_name','prefix','nameservers','host_ids'}
    if not isinstance(data,dict) or set(data)!=fields or type(data['schema']) is not int or data['schema']!=1:
        raise NetworkError('validation')
    owner_authorized(data['owner_user_id'])
    row=ProviderCredential.objects.get(pk=data['credential_id'])
    if type(data['credential_revision']) is not int or row.revision!=data['credential_revision']:
        raise NetworkError('conflict')
    cid='provider:'+str(row.pk)
    c=Connection(cid,'user:'+str(data['owner_user_id']),row.provider,row.account_id or cid,
                 cid+':'+str(row.revision),row.revision,'ready')
    b=ZoneBinding(data['binding_id'],c.owner_id,c.id,data['zone_id'],data['zone_name'],data['prefix'],
                  data['binding_revision'],'ready',data['nameservers'])
    if not isinstance(data['host_ids'],list) or not (0 if allow_empty else 1)<=len(data['host_ids'])<=256:
        raise NetworkError('validation')
    hosts=tuple(resource_uuid(v) for v in data['host_ids'])
    if len(set(hosts))!=len(hosts) or not b.nameservers:raise NetworkError('validation')
    return Selection(data['owner_user_id'],c,b,hosts)


class RegistryEvidenceSource:
    def __init__(self, selected, authority_collector, *, clock=None, use_observed_address=False, proposed_assignments=None, assignment_resolver=None):
        self.assignment_resolver=assignment_resolver
        self.selected,self.collector=selected,authority_collector
        self.proposed_assignments=proposed_assignments or {}
        self.use_observed_address=use_observed_address
        self.clock=clock or (lambda:timezone.now().timestamp())

    def current(self):
        selected=self.selected;c=selected.connection
        owner_authorized(selected.owner_user_id)
        if c.owner_id!='user:'+str(selected.owner_user_id) or not c.id.startswith('provider:'):
            raise NetworkError('permission')
        row=ProviderCredential.objects.get(pk=c.id.removeprefix('provider:'))
        if (row.provider,row.account_id or c.id,row.revision,c.id+':'+str(row.revision))!=(
                c.provider,c.account_ref,c.revision,c.credential_ref):raise NetworkError('conflict')
        return row

    def authority(self, connection, binding):
        self.current()
        if connection!=self.selected.connection or binding!=self.selected.binding:raise NetworkError('conflict')
        result=self.collector.authority(connection,binding)
        self.current()  # credential/administrator may have changed during DNS IO
        return result

    def host(self, owner_id, binding_id, resource_id):
        s=self.selected
        if (owner_id,binding_id)!=(s.connection.owner_id,s.binding.id) or resource_id not in s.host_ids:
            raise NetworkError('permission')
        # Consistent database snapshot, no network I/O under the transaction.
        with transaction.atomic():
            self.current()
            host=Host.objects.get(pk=resource_id)
            assignment=self.proposed_assignments.get(resource_id)
            if assignment is None:assignment=self.assignment_resolver(resource_id) if self.assignment_resolver else DnsAssignment.objects.get(host=host)
            if host.provider!='aws' or not assignment.name.endswith('.'+s.binding.prefix):
                raise NetworkError('permission')
            # Managed host names are one label below the explicitly selected prefix.
            if '.' in assignment.name[:-(len(s.binding.prefix)+1)]:raise NetworkError('permission')
            enrolled=CloudIdentity(host.account_id,host.region,host.instance_id)
            if not assignment.enabled:
                return HostEvidence(owner_id,binding_id,resource_id,assignment.revision,None,False,False,
                    enrolled,enrolled,enrolled,'','','',0,0,True)
            if host.archived_at or host.aws_missing_since:raise NetworkError('permission')
            key=HostIdentity.objects.filter(host=host,status='approved',fingerprint=host.signed_dns_fingerprint).first()
            if not key or not host.signed_dns_observed_at or host.signed_dns_observed_at<key.approved_at:
                raise NetworkError('permission')
            scopes=('region-discovery',host.account_id+'/region-discovery',host.account_id+'/'+host.region)
            scans=list(InventoryScan.objects.filter(scope__in=scopes))
            now=self.clock()
            if len(scans)!=3 or any(r.error or not r.last_success or not fresh(r.last_success.timestamp(),now) for r in scans):
                raise NetworkError('permission')
            if not host.aws_checked_at or not fresh(host.aws_checked_at.timestamp(),now):raise NetworkError('permission')
            try:
                observed=datetime.fromisoformat(host.aws_observation['observed_at'])
                if timezone.is_naive(observed):raise ValueError()
                inventory=CloudIdentity(**host.aws_observation['cloud'])
                signed=CloudIdentity(**host.signed_dns_report['cloud'])
                signed_address=host.signed_dns_report['public_ip']
                inventory_address=host.aws_observation['public_ip']
                if not self.use_observed_address and assignment.desired_action!='present':raise NetworkError('permission')
                desired=RecordSnapshot(assignment.name,inventory_address if self.use_observed_address else assignment.desired_address,300 if s.connection.provider=='cloudflare' else 600)
            except (KeyError,TypeError,ValueError):raise NetworkError('permission') from None
            return HostEvidence(owner_id,binding_id,resource_id,assignment.revision,desired,True,True,
                enrolled,signed,inventory,signed_address,inventory_address,host.aws_observation.get('state',''),
                host.signed_dns_observed_at.timestamp(),observed.timestamp())


class RegistrySecretResolver:
    def __init__(self, source):self.source=source
    def resolve(self, owner_id, connection_id, credential_ref):
        c=self.source.selected.connection
        if (owner_id,connection_id,credential_ref)!=(c.owner_id,c.id,c.credential_ref):raise NetworkError('permission')
        from .setup_configuration import decrypt_provider
        row=self.source.current()
        try:values=decrypt_provider(row)
        except Exception:raise NetworkError('authentication') from None
        self.source.current()
        return values


def readiness(selected, *, collector=None, provider_factory=None):
    """Diagnostic only: ready evidence neither adopts records nor enables writes."""
    if collector is None:
        from zog.network_register.dns_authority import DnsAuthorityCollector
        collector=DnsAuthorityCollector()
    source=RegistryEvidenceSource(selected,collector)
    gate=EvidenceGate(source)
    c,b=selected.connection,selected.binding
    evidence=gate.authority(c,b)
    # Reuse the collected observations, never renew their timestamps. Avoid
    # repeating a full DNS walk for every host; the gate still checks freshness.
    class Collected:
        def authority(self,*_):return evidence
    source.collector=Collected()
    ReadOnlyConnectionValidator(gate,RegistrySecretResolver(source),provider_factory=provider_factory).validate(c,(b,))
    rows=[]
    for resource in selected.host_ids:
        try:
            host=source.host(c.owner_id,b.id,resource)
            action='publish' if host.publish_enabled else 'unpublish'
            gate.check(c,b,resource,host.desired,action,host.desired_revision)
            rows.append(dict(host_id=resource,evidence='ready',desired_revision=host.desired_revision,
                             intent=action,adoption='requires-explicit-review'))
        except (NetworkError,Host.DoesNotExist,DnsAssignment.DoesNotExist,ValueError):
            rows.append(dict(host_id=resource,evidence='blocked',reason='host-evidence-unavailable'))
    source.current()
    gate.authority(c,b)  # do not return a report whose DNS evidence expired during reads
    return dict(mode='read-only',writes_enabled=False,owner_id=c.owner_id,binding_id=b.id,
                authority='verified',provider_reads='verified',write_permission='unknown',hosts=rows)
