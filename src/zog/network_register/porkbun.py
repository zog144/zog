"""Porkbun onboarding reads. No purchase, funding, renewal or DNS mutations."""
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from .client import NoRedirect
from .operations import domain_name


class PorkbunError(RuntimeError):
    """Sanitized provider/transport failure; never includes a request or response body."""


def credentials(path=None):
    if path:
        values = {}
        lines = Path(path).read_text().splitlines()
        pending = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower()
                if key not in ('api key', 'secret key', 'secret api key'):
                    raise ValueError('Unknown Porkbun credential label')
                key = 'secret key' if key == 'secret api key' else key
                if key in values:
                    raise ValueError('Duplicate Porkbun credential label')
                values[key] = value.strip()
                pending = key if not value.strip() else None
            elif pending:
                values[pending] = line
                pending = None
            else:
                raise ValueError('Expected labelled Porkbun API key and secret key')
        pair = values.get('api key'), values.get('secret key')
    else:
        pair = os.getenv('PORKBUN_API_KEY'), os.getenv('PORKBUN_SECRET_API_KEY')
    _validate_keys(*pair)
    return pair


def _validate_keys(api_key, secret_key):
    if any(not isinstance(v, str) or not 1 <= len(v) <= 4096 or any(c.isspace() for c in v) for v in (api_key, secret_key)):
        raise ValueError('Supply both Porkbun API key and secret API key')


class PorkbunClient:
    def __init__(self, api_key, secret_key):
        _validate_keys(api_key, secret_key)
        self._api_key, self._secret_key = api_key, secret_key
        self._opener = urllib.request.build_opener(NoRedirect())

    def _read(self, path, parameters=None):
        # Porkbun supports POST for these read operations. The allowlist prevents
        # this onboarding client being used for billing or provider mutations.
        if path not in ('/ping', '/domain/listAll') and not re.fullmatch(r'/dns/retrieve/[a-z0-9.-]+', path):
            raise ValueError('Unsupported Porkbun read endpoint')
        body = dict(parameters or {})
        body.update(apikey=self._api_key, secretapikey=self._secret_key)
        request = urllib.request.Request('https://api.porkbun.com/api/json/v3' + path,
            data=json.dumps(body).encode(), method='POST', headers={'Content-Type':'application/json'})
        try:
            with self._opener.open(request, timeout=25) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise PorkbunError('Porkbun response exceeded size limit')
            result = json.loads(raw)
        except urllib.error.HTTPError as error:
            raise PorkbunError(f'Porkbun HTTP {error.code}; check credentials, API access and network access') from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise PorkbunError('Porkbun transport failure') from None
        except (ValueError, UnicodeError):
            raise PorkbunError('Invalid Porkbun response') from None
        if not isinstance(result, dict) or result.get('status') != 'SUCCESS':
            raise PorkbunError('Porkbun rejected the read request; check credentials and domain API access')
        return result

    def verify(self):
        self._read('/ping')
        return {'authenticated': True, 'provider': 'porkbun'}

    def list_domains(self, start=0):
        if type(start) is not int or start < 0:
            raise ValueError('Domain offset must be a nonnegative integer')
        payload = self._read('/domain/listAll', {'start':start})
        rows = payload.get('domains')
        if not isinstance(rows, list) or len(rows) > 1000:
            raise PorkbunError('Invalid Porkbun domain list')
        domains, seen = [], set()
        for row in rows:
            try:
                name = domain_name(row['domain'])
                if name in seen:
                    raise ValueError('Duplicate domain')
                seen.add(name)
                # Do not equate account membership or apiAccess with active DNS,
                # successful delegation, or proven DNS-write permission.
                access = row.get('apiAccess')
                domains.append({'id':name, 'name':name, 'status':'listed',
                    'api_access': True if access in (True, 'yes', '1') else False if access in (False, 'no', '0') else None})
            except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
                raise PorkbunError('Invalid Porkbun domain data') from None
        return {'domains':sorted(domains, key=lambda r:r['name']), 'more_available':len(rows)==1000,
                'next_start': start+len(rows) if len(rows)==1000 else None}

    def records(self, domain):
        domain = domain_name(domain)
        payload = self._read('/dns/retrieve/' + domain)
        rows = payload.get('records')
        if not isinstance(rows, list):
            raise PorkbunError('Invalid Porkbun DNS record list')
        return rows
