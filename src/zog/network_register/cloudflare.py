"""Cloudflare DNS adapter for the shared executor. No retries or registrar routes."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from .client import NoRedirect
from .contracts import Capability, NetworkError, Page
from .models import canonical, RecordSnapshot, observation_name

BASE = 'https://api.cloudflare.com/client/v4'
LIMIT = 2 * 1024 * 1024


def provider_id(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{32}', value):
        raise NetworkError('validation')
    return value


class CloudflareTransport:
    def request(self, method, url, *, headers, body, timeout):
        if not url.startswith(BASE + '/'):
            raise NetworkError('validation')
        request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
        try:
            response = urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error
        except (urllib.error.URLError, OSError, TimeoutError):
            raise NetworkError('transient' if method == 'GET' else 'uncertain') from None
        with response:
            try: data = response.read(LIMIT + 1)
            except (OSError, TimeoutError):
                raise NetworkError('transient' if method == 'GET' else 'uncertain') from None
            if len(data) > LIMIT: raise NetworkError('validation' if method == 'GET' else 'uncertain')
            return response.code, dict(response.headers), data


def retry_after(headers):
    value = {k.lower(): v for k, v in headers.items()}.get('retry-after')
    if value is None: return None
    try:
        return max(0, int(value))
    except (ValueError, TypeError):
        try: return max(0, int((parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()) + 1)
        except (ValueError, TypeError, OverflowError): return None


class CloudflareDns:
    def __init__(self, connection, secrets, transport=None):
        if connection.provider != 'cloudflare': raise NetworkError('unsupported')
        provider_id(connection.account_ref)
        self.connection, self.secrets = connection, secrets
        self.transport = transport or CloudflareTransport()

    def _request(self, method, path, body=None, query=None):
        secrets = self.secrets.resolve(self.connection.owner_id, self.connection.id, self.connection.credential_ref)
        if set(secrets) != {'api_token'} or not isinstance(secrets['api_token'], str) or not secrets['api_token'] or any(c.isspace() for c in secrets['api_token']):
            raise NetworkError('authentication')
        url = BASE + path + ('?' + urllib.parse.urlencode(query) if query else '')
        try:
            status, headers, raw = self.transport.request(method, url,
                headers={'Authorization': 'Bearer ' + secrets['api_token'], 'Content-Type': 'application/json'},
                body=None if body is None else json.dumps(body).encode(), timeout=25)
        except NetworkError: raise
        except (OSError, TimeoutError):
            raise NetworkError('transient' if method == 'GET' else 'uncertain') from None
        category = {401: 'authentication', 403: 'permission', 404: 'not-found', 409: 'conflict', 429: 'rate-limit'}.get(status)
        if category: raise NetworkError(category, retry_after=retry_after(headers))
        if status >= 500: raise NetworkError('transient' if method == 'GET' else 'uncertain', retry_after=retry_after(headers))
        if not 200 <= status < 300: raise NetworkError('validation' if method == 'GET' else 'uncertain')
        try:
            if len(raw) > LIMIT: raise ValueError()
            payload = json.loads(raw)
            if not isinstance(payload, dict) or payload.get('success') is not True or 'result' not in payload:
                raise ValueError()
        except (ValueError, TypeError, UnicodeError):
            raise NetworkError('validation' if method == 'GET' else 'uncertain') from None
        return payload

    def inspect_connection(self):
        self.list_zones()
        return {'read': Capability(True, True, True, 'zone-list-read'),
                'write_a': Capability(True, None, None, 'target-write-access-unverified')}

    def _page(self, path, cursor=None, query=None):
        if cursor is not None and (not isinstance(cursor, str) or not re.fullmatch('[1-9][0-9]{0,3}', cursor)):
            raise NetworkError('validation')
        page = int(cursor or '1')
        payload = self._request('GET', path, query=dict(query or {}, page=page, per_page=100))
        info, rows = payload.get('result_info'), payload['result']
        if not isinstance(info, dict) or not isinstance(rows, list) or len(rows) > 100:
            raise NetworkError('validation')
        total = info.get('total_pages')
        if (type(total) is not int or not 0 <= total <= 1000 or type(info.get('page')) is not int
                or info['page'] != page or page > max(1, total) or (total == 0 and rows)):
            raise NetworkError('validation')
        if total > page and not rows: raise NetworkError('validation')
        return Page(tuple(rows), str(page + 1) if page < total else None)

    def list_zones(self, cursor=None):
        page = self._page('/zones', cursor, {'account.id': self.connection.account_ref})
        for zone in page.items: self._zone(zone)
        return page

    def _zone(self, zone):
        if not isinstance(zone, dict) or not isinstance(zone.get('account'), dict) or zone['account'].get('id') != self.connection.account_ref:
            raise NetworkError('permission')
        provider_id(zone.get('id'))
        try: canonical(zone['name'])
        except (KeyError, ValueError, UnicodeError): raise NetworkError('validation') from None
        return zone

    def get_zone(self, zone_id):
        zone = self._zone(self._request('GET', '/zones/' + provider_id(zone_id))['result'])
        if zone['id'] != zone_id: raise NetworkError('conflict')
        return zone

    @staticmethod
    def _record(record):
        if not isinstance(record, dict): raise NetworkError('validation')
        provider_id(record.get('id'))
        try:
            observation_name(record['name'])
            if not isinstance(record['type'], str) or not record['type']: raise ValueError()
        except (KeyError, ValueError, UnicodeError): raise NetworkError('validation') from None
        return record  # Preserve unknown types for inspection and conflict detection.

    def list_records(self, zone_id, cursor=None):
        page = self._page('/zones/' + provider_id(zone_id) + '/dns_records', cursor)
        for record in page.items: self._record(record)
        return page

    def get_record(self, zone_id, record_id):
        record = self._record(self._request('GET', '/zones/' + provider_id(zone_id) + '/dns_records/' + provider_id(record_id))['result'])
        if record['id'] != record_id: raise NetworkError('conflict')
        return record

    @staticmethod
    def _body(record, marker):
        if not isinstance(record, RecordSnapshot) or record.ttl < 300 or not re.fullmatch(r'zog-operation:[0-9a-f-]{36}', marker):
            raise NetworkError('validation')
        return dict(type='A', name=record.name, content=record.address, ttl=record.ttl, proxied=False, comment=marker)

    def create_record(self, zone_id, record, *, marker, idempotency_key):
        return self._record(self._request('POST', '/zones/' + provider_id(zone_id) + '/dns_records', self._body(record, marker))['result'])

    def update_record(self, zone_id, record_id, record, *, marker, idempotency_key):
        return self._record(self._request('PATCH', '/zones/' + provider_id(zone_id) + '/dns_records/' + provider_id(record_id), self._body(record, marker))['result'])

    def delete_record(self, zone_id, record_id, *, idempotency_key):
        self._request('DELETE', '/zones/' + provider_id(zone_id) + '/dns_records/' + provider_id(record_id))
