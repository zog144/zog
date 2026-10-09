"""Concrete fail-closed publication policy over trusted DNS and host observations.

Sources must be privileged collectors, never arbitrary browser/beacon JSON. This
module validates evidence; it does not pretend an API zone status is DNS authority.
"""
from dataclasses import dataclass
import time
from typing import Protocol
from .contracts import NetworkError
from .models import canonical, identifier, resource_uuid, timestamp, RecordSnapshot


@dataclass(frozen=True)
class AuthoritativeAnswer:
    nameserver: str
    soa_zone: str
    authoritative: bool
    observed_at: float
    prefix_unshadowed: bool

    def __post_init__(self):
        object.__setattr__(self, 'nameserver', canonical(self.nameserver))
        object.__setattr__(self, 'soa_zone', canonical(self.soa_zone))
        timestamp(self.observed_at)
        if type(self.authoritative) is not bool or type(self.prefix_unshadowed) is not bool:
            raise ValueError('Expected DNS evidence flags')


@dataclass(frozen=True)
class AuthorityEvidence:
    owner_id: str
    connection_id: str
    connection_revision: int
    credential_ref: str
    binding_id: str
    binding_revision: int
    zone_id: str
    zone_name: str
    prefix: str
    delegated_nameservers: tuple[str, ...]
    delegation_observed_at: float
    answers: tuple[AuthoritativeAnswer, ...]

    def __post_init__(self):
        from .models import revision
        for v in (self.owner_id,self.connection_id,self.credential_ref,self.binding_id,self.zone_id):identifier(v)
        revision(self.connection_revision);revision(self.binding_revision)
        for field in ('zone_name','prefix'):object.__setattr__(self,field,canonical(getattr(self,field)))
        timestamp(self.delegation_observed_at)
        if not isinstance(self.delegated_nameservers,(tuple,list)) or not isinstance(self.answers,(tuple,list)):
            raise ValueError('Expected DNS evidence sequences')
        names = tuple(sorted(canonical(v) for v in self.delegated_nameservers))
        if not names or len(names)>16 or len(set(names))!=len(names):raise ValueError('Invalid delegation set')
        if not self.answers or len(self.answers)>16 or any(not isinstance(v,AuthoritativeAnswer) for v in self.answers):
            raise ValueError('Invalid authoritative answers')
        object.__setattr__(self,'delegated_nameservers',names)
        object.__setattr__(self,'answers',tuple(self.answers))


@dataclass(frozen=True)
class CloudIdentity:
    account_id: str
    region: str
    instance_id: str

    def __post_init__(self):
        for v in (self.account_id,self.region,self.instance_id):identifier(v)


@dataclass(frozen=True)
class HostEvidence:
    owner_id: str
    binding_id: str
    resource_id: str
    desired_revision: int
    desired: RecordSnapshot | None
    publish_enabled: bool
    enrolled: bool
    enrolled_identity: CloudIdentity
    signed_identity: CloudIdentity
    inventory_identity: CloudIdentity
    signed_address: str
    inventory_address: str
    inventory_state: str
    signed_observed_at: float
    inventory_observed_at: float
    explicit_unpublish: bool = False

    def __post_init__(self):
        from .models import revision
        identifier(self.owner_id);identifier(self.binding_id)
        object.__setattr__(self,'resource_id',resource_uuid(self.resource_id));revision(self.desired_revision)
        if self.desired is not None and not isinstance(self.desired,RecordSnapshot):raise ValueError('Invalid desired record')
        for v in (self.publish_enabled,self.enrolled,self.explicit_unpublish):
            if type(v) is not bool:raise ValueError('Expected host evidence flags')
        for v in (self.enrolled_identity,self.signed_identity,self.inventory_identity):
            if not isinstance(v,CloudIdentity):raise ValueError('Expected cloud identity')
        timestamp(self.signed_observed_at);timestamp(self.inventory_observed_at)


class EvidenceSource(Protocol):
    def authority(self, connection, binding) -> AuthorityEvidence: ...
    def host(self, owner_id: str, binding_id: str, resource_id: str) -> HostEvidence: ...


def fresh(stamp, now):
    return 0 <= now - stamp <= 300


class EvidenceGate:
    def __init__(self, source: EvidenceSource, clock=time.time):
        self.source, self.clock = source, clock

    def authority(self, connection, binding):
        """Also used to validate candidate credentials before activation/rotation."""
        evidence=self.source.authority(connection,binding)
        now=self.clock();timestamp(now)
        if not isinstance(evidence,AuthorityEvidence):raise NetworkError('permission')
        expected=(connection.owner_id,connection.id,connection.revision,connection.credential_ref,
                  binding.id,binding.revision,binding.zone_id,binding.zone_name,binding.prefix)
        observed=(evidence.owner_id,evidence.connection_id,evidence.connection_revision,evidence.credential_ref,
                  evidence.binding_id,evidence.binding_revision,evidence.zone_id,evidence.zone_name,evidence.prefix)
        if expected!=observed:raise NetworkError('conflict')
        if not binding.nameservers or evidence.delegated_nameservers!=binding.nameservers:
            raise NetworkError('conflict')
        if not fresh(evidence.delegation_observed_at,now):raise NetworkError('permission')
        answers={v.nameserver:v for v in evidence.answers}
        if len(answers)!=len(evidence.answers) or set(answers)!=set(binding.nameservers):raise NetworkError('conflict')
        if any(not v.authoritative or not v.prefix_unshadowed or v.soa_zone!=binding.zone_name or not fresh(v.observed_at,now)
               for v in answers.values()):raise NetworkError('permission')
        return evidence

    def check(self, connection, binding, resource_id, desired, action, desired_revision):
        if connection.owner_id!=binding.owner_id or connection.id!=binding.connection_id:
            raise NetworkError('permission')
        if connection.status!='ready' or binding.status not in ('ready','blocked'):
            raise NetworkError('permission')
        evidence=self.authority(connection,binding)
        if action=='inspect':return
        if action not in ('publish','unpublish') or binding.status!='ready':raise NetworkError('permission')
        self.check_host(connection,binding,resource_id,desired,action,desired_revision)
        now=self.clock()
        if not fresh(evidence.delegation_observed_at,now) or any(not fresh(v.observed_at,now) for v in evidence.answers):
            raise NetworkError('permission')

    def check_host(self, connection, binding, resource_id, desired, action, desired_revision):
        """Host policy only; initialization callers must separately verify delegation.

        Does not claim zone authority or replace check() for reconciliation.
        """
        if (connection.owner_id!=binding.owner_id or connection.id!=binding.connection_id
                or connection.status!='ready' or binding.status!='ready'
                or action not in ('publish','unpublish')):
            raise NetworkError('permission')
        if type(desired_revision) is not int or desired_revision<1:raise NetworkError('validation')
        host=self.source.host(connection.owner_id,binding.id,resource_uuid(resource_id))
        now=self.clock();timestamp(now)
        if not isinstance(host,HostEvidence):raise NetworkError('permission')
        if (host.owner_id,host.binding_id,host.resource_id,host.desired_revision)!=(connection.owner_id,binding.id,resource_uuid(resource_id),desired_revision):
            raise NetworkError('conflict')
        if action=='unpublish':
            if desired is not None or host.desired is not None or host.publish_enabled or not host.explicit_unpublish:
                raise NetworkError('permission')
            return  # explicit retirement does not require a still-running host
        if desired!=host.desired or not isinstance(desired,RecordSnapshot):raise NetworkError('conflict')
        now=self.clock();timestamp(now)
        if (not host.enrolled or not host.publish_enabled or host.explicit_unpublish or host.inventory_state!='running'
                or host.enrolled_identity!=host.signed_identity or host.enrolled_identity!=host.inventory_identity
                or host.signed_address!=desired.address or host.inventory_address!=desired.address
                or not fresh(host.signed_observed_at,now) or not fresh(host.inventory_observed_at,now)):
            raise NetworkError('permission')
