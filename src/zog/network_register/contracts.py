"""Provider-neutral boundaries. These protocols perform no IO themselves."""
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence


ERROR_CODES = frozenset({'authentication', 'permission', 'validation', 'conflict',
    'not-found', 'rate-limit', 'transient', 'uncertain', 'storage', 'unsupported'})


class NetworkError(RuntimeError):
    """Safe public error. Raw provider messages/bodies must never be passed here."""
    def __init__(self, code: str, *, request_id: str | None = None,
                 provider_code: str | None = None, retry_after: int | None = None):
        if code not in ERROR_CODES:
            raise ValueError('Unknown error category')
        import re
        for value in (request_id, provider_code):
            if value is not None and (not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value)):
                raise ValueError('Invalid sanitized error identifier')
        if retry_after is not None and (type(retry_after) is not int or retry_after < 0):
            raise ValueError('Invalid retry interval')
        self.code, self.request_id, self.provider_code, self.retry_after = code, request_id, provider_code, retry_after
        super().__init__('network-register: ' + code)


class ProviderWriteWarning(NetworkError):
    """Provider accepted a write with an authority warning; operator review needed."""
    def __init__(self, record_id=None):
        super().__init__('conflict')
        self.record_id = record_id


@dataclass(frozen=True)
class Capability:
    supported: bool | None
    authorized: bool | None
    ready: bool | None
    reason: str

    def __post_init__(self):
        if any(v is not None and type(v) is not bool for v in (self.supported, self.authorized, self.ready)):
            raise ValueError('Capability values must be true, false or unknown')
        if not isinstance(self.reason, str) or not self.reason or len(self.reason) > 256:
            raise ValueError('Capability needs a safe reason')
        if self.ready is True and (self.supported is not True or self.authorized is not True):
            raise ValueError('Readiness requires support and authorization')


@dataclass(frozen=True)
class Page:
    items: tuple
    next_cursor: str | None = None


class HttpTransport(Protocol):
    def request(self, method: str, url: str, *, headers: Mapping[str, str],
                body: bytes | None, timeout: float) -> tuple[int, Mapping[str, str], bytes]: ...


class SecretResolver(Protocol):
    def resolve(self, owner_id: str, connection_id: str, credential_ref: str) -> Mapping[str, str]: ...


class DnsProvider(Protocol):
    def inspect_connection(self) -> Mapping[str, Capability]: ...
    def list_zones(self, cursor: str | None = None) -> Page: ...
    def get_zone(self, zone_id: str) -> Mapping: ...
    def list_records(self, zone_id: str, cursor: str | None = None) -> Page: ...
    def get_record(self, zone_id: str, record_id: str) -> Mapping: ...
    def create_record(self, zone_id: str, record, *, marker: str, idempotency_key: str) -> Mapping: ...
    def update_record(self, zone_id: str, record_id: str, record, *, marker: str, idempotency_key: str) -> Mapping: ...
    def delete_record(self, zone_id: str, record_id: str, *, idempotency_key: str) -> None: ...


class RegistrarReader(Protocol):
    def list_registrations(self, cursor: str | None = None) -> Page: ...


class ZoneProvisioner(Protocol):
    def create_zone(self, account_ref: str, name: str, *, operation_id: str) -> Mapping: ...


class Authorizer(Protocol):
    def authorize(self, actor: str, owner_id: str, connection, binding, action: str) -> bool: ...


class PublicationGate(Protocol):
    """Trusted integration checks fresh authority/evidence; must raise on failure.

    publish requires enrolled identity, matching fresh inventory and public address;
    unpublish requires explicit intent. inspect verifies current DNS authority only.
    This interface has no permissive default implementation.
    """
    def check(self, connection, binding, resource_id: str, desired, action: str,
              desired_revision: int | None) -> None: ...


class StateStore(Protocol):
    """Transactions must serialize read/compare/write and commit durably or raise.

    read/write accept only validated JSON DTOs, never credentials. A store adapter
    supplied by station-access must preserve the same transaction/rollback semantics.
    """
    def transaction(self): ...
    def read(self, kind: str, key: str) -> dict | None: ...
    def write(self, kind: str, key: str, value: dict) -> None: ...
    def delete(self, kind: str, key: str) -> None: ...
    def all(self, kind: str) -> Sequence[dict]: ...
    def worker_lock(self): ...
