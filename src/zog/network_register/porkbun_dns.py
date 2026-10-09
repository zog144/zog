"""Native Porkbun DNS only. No billing, registrar mutation or bulk RRset routes."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from .client import NoRedirect
from .cloudflare import retry_after
from .contracts import Capability, NetworkError, Page, ProviderWriteWarning
from .models import RecordSnapshot, canonical, below, observation_name

BASE = 'https://api.porkbun.com/api/json/v3'
LIMIT = 2 * 1024 * 1024
ERRORS = {
    'API_KEY_REQUIRED': 'authentication', 'INVALID_API_KEYS_001': 'authentication',
    'INVALID_TOKEN': 'authentication', 'INVALID_USER': 'authentication',
    'IP_NOT_ALLOWED': 'permission', 'DOMAIN_NOT_ALLOWED': 'permission',
    'DOMAIN_NOT_FOUND': 'not-found', 'INVALID_DOMAIN': 'permission',
    'INVALID_RECORD_ID': 'not-found', 'DUPLICATE_RECORD': 'conflict',
    'RATE_LIMIT_EXCEEDED': 'rate-limit', 'IDEMPOTENCY_KEY_MISMATCH': 'conflict',
    'IDEMPOTENCY_KEY_IN_USE': 'uncertain',
}


def record_id(value):
    if type(value) is int: value = str(value)
    if not isinstance(value, str) or not re.fullmatch('[0-9]{1,32}', value): raise NetworkError('validation')
    return value


class PorkbunTransport:
    def request(self, method, url, *, headers, body, timeout):
        if not url.startswith(BASE + '/'): raise NetworkError('validation')
        request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
        try:
            response = urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout)
        except urllib.error.HTTPError as error: response = error
        except (urllib.error.URLError, OSError, TimeoutError):
            raise NetworkError('transient' if method == 'GET' else 'uncertain') from None
        with response:
            try: raw = response.read(LIMIT + 1)
            except (OSError, TimeoutError):
                raise NetworkError('transient' if method == 'GET' else 'uncertain') from None
            if len(raw) > LIMIT: raise NetworkError('validation' if method == 'GET' else 'uncertain')
            return response.code, dict(response.headers), raw


class PorkbunDns:
    def __init__(self, connection, secrets, transport=None):
        if connection.provider != 'porkbun': raise NetworkError('unsupported')
        self.connection, self.secrets = connection, secrets
        self.transport = transport or PorkbunTransport()

    def _request(self, method, path, body=None, key=None, query=None):
        # Validate the route even for internal calls; no generic provider escape hatch.
        read = path == '/domain/listAll' or re.fullmatch(r'/dns/(?:preflight|retrieve)/[a-z0-9.-]+(?:/[0-9]+)?', path)
        write = re.fullmatch(r'/dns/(?:create/[a-z0-9.-]+|(?:edit|delete)/[a-z0-9.-]+/[0-9]+)', path)
        if not ((method == 'GET' and read and key is None and body is None) or (method == 'POST' and write)):
            raise NetworkError('unsupported')
        values = self.secrets.resolve(self.connection.owner_id, self.connection.id, self.connection.credential_ref)
        if (not isinstance(values, dict) or set(values) != {'api_key', 'secret_key'} or
                any(not isinstance(v, str) or not 1 <= len(v) <= 4096 or any(c.isspace() for c in v) for v in values.values())):
            raise NetworkError('authentication')
        headers = {'Content-Type': 'application/json', 'X-API-Key': values['api_key'], 'X-Secret-API-Key': values['secret_key']}
        if method == 'POST':
            if not isinstance(key, str) or not re.fullmatch('[0-9a-f]{64}', key): raise NetworkError('validation')
            headers['Idempotency-Key'] = key
        url = BASE + path + ('?' + urllib.parse.urlencode(query) if query else '')
        try:
            status, response_headers, raw = self.transport.request(method, url, headers=headers,
                body=None if method == 'GET' else json.dumps(body or {}, sort_keys=True, separators=(',', ':')).encode(), timeout=25)
        except NetworkError: raise
        except (OSError, TimeoutError): raise NetworkError('transient' if method == 'GET' else 'uncertain') from None
        delay = retry_after(response_headers)
        category = {401: 'authentication', 403: 'permission', 404: 'not-found', 409: 'conflict', 429: 'rate-limit'}.get(status)
        if category: raise NetworkError(category, retry_after=delay)
        if status >= 500: raise NetworkError('transient' if method == 'GET' else 'uncertain', retry_after=delay)
        try:
            if len(raw) > LIMIT: raise ValueError()
            payload = json.loads(raw)
            if not isinstance(payload, dict): raise ValueError()
        except (ValueError, TypeError, UnicodeError):
            raise NetworkError('validation' if method == 'GET' else 'uncertain') from None
        if not 200 <= status < 300 or payload.get('status') != 'SUCCESS':
            code = payload.get('code')
            category = ERRORS.get(code, 'validation' if method == 'GET' else 'uncertain') if isinstance(code, str) else ('validation' if method == 'GET' else 'uncertain')
            raise NetworkError(category, provider_code=code if isinstance(code, str) and code in ERRORS else None, retry_after=delay)
        if method == 'POST' and payload.get('warnings'):
            # Accepted write, but authority may have changed. Do not log raw warnings.
            observed_id = payload.get('id')
            try: observed_id = record_id(observed_id) if observed_id is not None else None
            except NetworkError: observed_id = None
            raise ProviderWriteWarning(observed_id)
        return payload

    def list_zones(self, cursor=None):
        if cursor is not None and (not isinstance(cursor, str) or not re.fullmatch('[0-9]{1,8}', cursor)):
            raise NetworkError('validation')
        start = int(cursor or '0')
        rows = self._request('GET', '/domain/listAll', query={'start': start}).get('domains')
        if not isinstance(rows, list) or len(rows) > 1000: raise NetworkError('validation')
        result, seen = [], set()
        for row in rows:
            try: domain = canonical(row['domain'])
            except (KeyError, TypeError, ValueError, UnicodeError): raise NetworkError('validation') from None
            if domain in seen: raise NetworkError('validation')
            seen.add(domain)
            result.append(dict(id=domain, name=domain, account={'id':self.connection.account_ref},
                               status='discovered', api_access=row.get('apiAccess') == 'yes'))
        return Page(tuple(result), str(start + len(rows)) if len(rows) == 1000 else None)

    def inspect_connection(self):
        self.list_zones()
        return {'read': Capability(True, True, True, 'domain-list-read'),
                'write_a': Capability(True, None, None, 'target-write-access-unverified')}

    def get_zone(self, zone_id):
        domain = canonical(zone_id)
        payload = self._request('GET', '/dns/preflight/' + domain)
        checks = payload.get('checks')
        if payload.get('domain') != domain or not isinstance(checks, list): raise NetworkError('validation')
        authority = [c for c in checks if isinstance(c, dict) and c.get('id') == 'nameservers-ours']
        if len(authority) != 1 or authority[0].get('ok') is not True: raise NetworkError('conflict')
        return dict(id=domain, name=domain, account={'id':self.connection.account_ref}, status='active')

    def _records(self, domain, suffix=''):
        payload = self._request('GET', '/dns/retrieve/' + domain + suffix)
        # This flag also describes Porkbun's internal managed backend.
        # Authority is established by preflight plus the external DNS gate.
        if payload.get('cloudflare') not in ('disabled','enabled'): raise NetworkError('validation')
        if payload['cloudflare']=='enabled':
            if getattr(self,'require_native_inventory',False):raise NetworkError('conflict')
            self.get_zone(domain)
        rows = payload.get('records')
        if not isinstance(rows, list) or len(rows) > 10000: raise NetworkError('validation')
        result, seen = [], set()
        for row in rows:
            try:
                rid = record_id(row['id']); name = observation_name(row['name'])
                if rid in seen or (name != domain and not below(name, domain)): raise ValueError()
                if not isinstance(row['type'], str) or not row['type']: raise ValueError()
                ttl = row.get('ttl')
                if isinstance(ttl, str) and re.fullmatch('[0-9]{1,8}', ttl): ttl = int(ttl)
                if type(ttl) is not int or ttl < 1: raise ValueError()
                if row.get('proxied',False) is not False:raise NetworkError('conflict')
                notes = row.get('notes')
                if notes is not None and not isinstance(notes, str): raise ValueError()
                seen.add(rid)
                result.append(dict(row, id=rid, name=name, ttl=ttl, comment=notes, proxied=False))
            except (ValueError, TypeError, KeyError, UnicodeError): raise NetworkError('validation') from None
        return result

    def list_records(self, zone_id, cursor=None):
        if cursor is not None: raise NetworkError('validation')
        return Page(tuple(self._records(canonical(zone_id))))

    def get_record(self, zone_id, identifier):
        rid = record_id(identifier)
        rows = self._records(canonical(zone_id), '/' + rid)
        if len(rows) != 1 or rows[0]['id'] != rid: raise NetworkError('not-found')
        return rows[0]

    @staticmethod
    def _body(domain, record, marker):
        if not isinstance(record, RecordSnapshot) or not below(record.name, domain) or record.ttl < 600:
            raise NetworkError('validation')
        if not isinstance(marker, str) or not re.fullmatch(r'zog-operation:[0-9a-f-]{36}', marker): raise NetworkError('validation')
        return dict(name=record.name[:-(len(domain)+1)], type='A', content=record.address, ttl=record.ttl, notes=marker)

    def create_record(self, zone_id, record, *, marker, idempotency_key):
        domain = canonical(zone_id)
        result = self._request('POST', '/dns/create/' + domain, self._body(domain, record, marker), idempotency_key)
        return {'id':record_id(result.get('id'))}

    def update_record(self, zone_id, identifier, record, *, marker, idempotency_key):
        domain, rid = canonical(zone_id), record_id(identifier)
        self._request('POST', '/dns/edit/' + domain + '/' + rid, self._body(domain, record, marker), idempotency_key)
        return {'id':rid}

    def delete_record(self, zone_id, identifier, *, idempotency_key):
        self._request('POST', '/dns/delete/' + canonical(zone_id) + '/' + record_id(identifier), {}, idempotency_key)
