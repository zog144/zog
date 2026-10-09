"""Validated immutable shared DTOs. No provider secrets or arbitrary payloads."""
from dataclasses import asdict, dataclass
import ipaddress
import re
import uuid
from .operations import domain_name


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}', value):
        raise ValueError('Invalid opaque identifier')
    return value


def revision(value):
    if type(value) is not int or value < 1:
        raise ValueError('Revision must be a positive integer')


def resource_uuid(value):
    if not isinstance(value, str): raise ValueError('Expected resource UUID')
    return str(uuid.UUID(value))


def canonical(value):
    if not isinstance(value, str):
        raise ValueError('Expected DNS name')
    return domain_name(value)


def below(name, suffix):
    return name.endswith('.' + suffix)


def observation_name(value):
    """Normalize inspected DNS names, including service labels and wildcards.

    Write targets continue to use the stricter host-name canonical() validator.
    """
    if not isinstance(value, str): raise ValueError('Expected DNS name')
    name = value.rstrip('.').encode('idna').decode().lower()
    labels = name.split('.')
    if len(name) > 253 or len(labels) < 2: raise ValueError('Invalid DNS name')
    if labels[0] == '*': labels = labels[1:]
    if any(not re.fullmatch(r'[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?', label) for label in labels):
        raise ValueError('Invalid DNS name')
    return name


@dataclass(frozen=True)
class Connection:
    id: str
    owner_id: str
    provider: str
    account_ref: str
    credential_ref: str
    revision: int = 1
    status: str = 'unverified'

    def __post_init__(self):
        for v in (self.id, self.owner_id, self.account_ref, self.credential_ref): identifier(v)
        revision(self.revision)
        if self.provider not in ('cloudflare', 'porkbun') or self.status not in ('unverified', 'ready', 'action-required', 'revoked', 'disconnected'):
            raise ValueError('Invalid connection')


@dataclass(frozen=True)
class ZoneBinding:
    id: str
    owner_id: str
    connection_id: str
    zone_id: str
    zone_name: str
    prefix: str
    revision: int = 1
    status: str = 'discovered'
    nameservers: tuple[str, ...] = ()

    def __post_init__(self):
        for v in (self.id, self.owner_id, self.connection_id, self.zone_id): identifier(v)
        revision(self.revision)
        object.__setattr__(self, 'zone_name', canonical(self.zone_name))
        object.__setattr__(self, 'prefix', canonical(self.prefix))
        if not below(self.prefix, self.zone_name): raise ValueError('Prefix must be below zone')
        if self.status not in ('discovered', 'pending-delegation', 'ready', 'blocked', 'detached'):
            raise ValueError('Invalid binding state')
        if not isinstance(self.nameservers, (tuple, list)): raise ValueError('Expected nameserver list')
        normalized = tuple(sorted(canonical(v) for v in self.nameservers))
        if len(normalized) > 16 or len(normalized) != len(set(normalized)): raise ValueError('Invalid nameservers')
        object.__setattr__(self, 'nameservers', normalized)


@dataclass(frozen=True)
class RecordSnapshot:
    name: str
    address: str
    ttl: int
    type: str = 'A'
    proxied: bool = False

    def __post_init__(self):
        object.__setattr__(self, 'name', canonical(self.name))
        address = ipaddress.IPv4Address(self.address)
        if not address.is_global: raise ValueError('Public IPv4 address required')
        object.__setattr__(self, 'address', str(address))
        if self.type != 'A' or self.proxied is not False: raise ValueError('Only DNS-only A writes are supported')
        if type(self.ttl) is not int or not 60 <= self.ttl <= 86400: raise ValueError('Invalid effective TTL')


@dataclass(frozen=True)
class ManagedRecord:
    id: str
    owner_id: str
    binding_id: str
    resource_id: str
    record_id: str
    last_applied: RecordSnapshot
    desired_revision: int
    observed_at: float
    marker: str | None = None

    def __post_init__(self):
        for v in (self.id, self.owner_id, self.binding_id, self.resource_id, self.record_id): identifier(v)
        object.__setattr__(self, 'resource_id', resource_uuid(self.resource_id))
        revision(self.desired_revision)
        if not isinstance(self.last_applied, RecordSnapshot): raise ValueError('Expected record snapshot')
        timestamp(self.observed_at)
        if self.marker is not None and not re.fullmatch(r'(?:zog-operation:[0-9a-f-]{36}|Zog network-register owner [0-9a-f]{64})', self.marker):
            raise ValueError('Invalid operation marker')


def timestamp(value):
    import math
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0: raise ValueError('Invalid timestamp')


@dataclass(frozen=True)
class Plan:
    owner_id: str
    binding_id: str
    resource_id: str
    connection_revision: int
    binding_revision: int
    desired_revision: int
    action: str
    before: RecordSnapshot | None
    after: RecordSnapshot | None
    record_id: str | None = None

    def __post_init__(self):
        for v in (self.owner_id, self.binding_id, self.resource_id): identifier(v)
        object.__setattr__(self, 'resource_id', resource_uuid(self.resource_id))
        for v in (self.connection_revision, self.binding_revision, self.desired_revision): revision(v)
        if self.record_id is not None: identifier(self.record_id)
        for v in (self.before, self.after):
            if v is not None and not isinstance(v, RecordSnapshot): raise ValueError('Expected snapshot')
        valid = {'create': self.before is None and self.after is not None and self.record_id is None,
                 'update': self.before is not None and self.after is not None and self.record_id is not None,
                 'delete': self.before is not None and self.after is None and self.record_id is not None}
        if not valid.get(self.action, False): raise ValueError('Invalid record action')
        if self.before and self.after and self.before.name != self.after.name: raise ValueError('Rename requires separate operations')

    def to_dict(self): return asdict(self)

    @classmethod
    def from_dict(cls, value):
        value = dict(value)
        for k in ('before', 'after'):
            if value[k] is not None: value[k] = RecordSnapshot(**value[k])
        return cls(**value)
