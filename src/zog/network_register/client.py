"""Cloudflare v4 client. No automatic replay of requests or credential logging."""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class CloudflareError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward a bearer credential to a redirect destination.


def credentials(path=None):
    if path:
        values = {}
        for line in Path(path).read_text().splitlines():
            if ':' in line:
                key, value = line.split(':', 1)
                values[key.strip().lower()] = value.strip()
        account, token = values.get('account id'), values.get('api token')
    else:
        account, token = os.getenv('CLOUDFLARE_ACCOUNT_ID'), os.getenv('CLOUDFLARE_API_TOKEN')
    if not account or not re.fullmatch(r'[0-9a-f]{32}', account) or not token or any(c.isspace() for c in token):
        raise ValueError('Supply Account ID and API token through a token file or environment')
    return account, token


class Client:
    def __init__(self, account, token):
        if not re.fullmatch(r'[0-9a-f]{32}', account):
            raise ValueError('Invalid account ID')
        self.account = account
        self._token = token
        self._opener = urllib.request.build_opener(NoRedirect())

    @property
    def registrar(self):
        return '/accounts/' + self.account + '/registrar'

    def request(self, method, path, body=None, query=None):
        if not path.startswith('/') or '?' in path or '#' in path:
            raise ValueError('Expected an API path with separate query parameters')
        url = 'https://api.cloudflare.com/client/v4' + path
        if query:
            url += '?' + urllib.parse.urlencode(query)
        req = urllib.request.Request(url, method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Authorization': 'Bearer ' + self._token, 'Content-Type': 'application/json'})
        try:
            with self._opener.open(req, timeout=40) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read()).get('errors', [])
            except (ValueError, UnicodeError):
                detail = 'Non-JSON API response'
            safe = json.dumps(detail).replace(self._token, '[REDACTED]')
            raise CloudflareError(f'Cloudflare HTTP {error.code}: {safe}') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise CloudflareError('Cloudflare transport failure; mutation outcome may be unknown') from None
        except (ValueError, UnicodeError):
            raise CloudflareError('Invalid Cloudflare response; mutation outcome may be unknown') from None
        if payload.get('success') is not True:
            safe = json.dumps(payload.get('errors', [])).replace(self._token, '[REDACTED]')
            raise CloudflareError('Cloudflare rejected request: ' + safe)
        return payload

    def result(self, method, path, body=None, query=None):
        return self.request(method, path, body, query)['result']

    def pages(self, path, query=None):
        query = dict(query or {})
        page = 1
        while True:
            payload = self.request('GET', path, query=query | {'page': page, 'per_page': 50})
            yield from payload['result']
            if page >= payload.get('result_info', {}).get('total_pages', 1):
                return
            page += 1

    def search(self, term):
        return self.result('GET', self.registrar + '/domain-search', query={'q': term, 'limit': 10})

    def check(self, domains):
        if not 1 <= len(domains) <= 20:
            raise ValueError('Check between 1 and 20 domains')
        return self.result('POST', self.registrar + '/domain-check', {'domains': domains})
