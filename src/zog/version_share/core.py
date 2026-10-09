"""Small, dependency-free GitHub source retrieval API."""
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


class ShareError(Exception):
    def __init__(self, code, message, outcome='not-applicable'):
        super().__init__(message)
        self.code, self.outcome = code, outcome


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    """Uses only api.github.com; redirects never forward the credential."""
    def __init__(self, token, opener=None, *, retries=2, sleeper=time.sleep):
        if not token or any(c.isspace() for c in token):
            raise ShareError('configuration', 'Token must be one nonempty line.')
        self._retries, self._sleep = retries, sleeper
        self._token = token
        self._opener = opener or urllib.request.build_opener(NoRedirect())

    @classmethod
    def from_file(cls, path):
        try:
            token = Path(path).read_text().strip()
        except (OSError, UnicodeError):
            raise ShareError('configuration', 'Cannot read token file.') from None
        return cls(token)

    def request(self, method, path, body=None):
        for attempt in range(self._retries + 1):
            try:
                return self._request_once(method, path, body)
            except ShareError as error:
                if method != 'GET' or not getattr(error, 'retryable', False) or attempt == self._retries:
                    raise
                delay = max(2 ** attempt, getattr(error, 'retry_after', 0))
                if delay > 5:
                    raise
                self._sleep(delay)

    def _request_once(self, method, path, body=None):
        if not path.startswith('/') or path.startswith('//'):
            raise ShareError('configuration', 'Expected API-relative path.')
        request = urllib.request.Request('https://api.github.com' + path,
            data=None if body is None else json.dumps(body).encode(), method=method,
            headers={'Authorization': 'Bearer ' + self._token,
                     'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json',
                     'X-GitHub-Api-Version': '2022-11-28',
                     'User-Agent': 'version-share/0.3.0'})
        mutation = method != 'GET'
        try:
            with self._opener.open(request, timeout=30) as response:
                raw = response.read(32 * 1024 * 1024 + 1)
                if len(raw) > 32 * 1024 * 1024:
                    raise ShareError('unsupported', 'API response exceeds 32 MiB limit.',
                                     'uncertain' if mutation else 'not-applicable')
                return json.loads(raw)
        except urllib.error.HTTPError as error:
            code = {401: 'authentication', 403: 'forbidden', 404: 'not-found',
                    409: 'conflict', 422: 'conflict', 429: 'rate-limit'}.get(error.code, 'remote')
            if error.headers.get('X-RateLimit-Remaining') == '0':
                code = 'rate-limit'
            outcome = 'uncertain' if mutation and error.code >= 500 else 'not-published'
            failure = ShareError(code, 'GitHub returned HTTP %s; response body withheld.' % error.code,
                                 outcome if mutation else 'not-applicable')
            failure.retryable = code == 'rate-limit' or error.code in (502, 503, 504)
            try:
                failure.retry_after = float(error.headers.get('Retry-After', '0'))
                if code == 'rate-limit' and error.headers.get('X-RateLimit-Reset'):
                    failure.retry_after = max(failure.retry_after, float(error.headers['X-RateLimit-Reset']) - time.time())
            except ValueError:
                failure.retry_after = 60
            raise failure from None
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
            failure = ShareError('network', 'Network connection failed; check network policy and connectivity.',
                                 'uncertain' if mutation else 'not-applicable')
            failure.retryable = True
            raise failure from None
        except (ValueError, UnicodeError):
            raise ShareError('remote', 'Invalid JSON response.',
                             'uncertain' if mutation else 'not-applicable') from None


def component(value):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', value) or value in ('.', '..'):
        raise ShareError('configuration', 'Invalid owner or repository name.')
    return value


def repository_path(owner, program):
    return '/repos/' + component(owner) + '/' + component(program)


def check_access(client, owner=None, program=None):
    user = client.request('GET', '/user')
    result = {'login': user['login'], 'authenticated': True,
              'write_access': 'unverified; a live mutation is required'}
    if program:
        repository = client.request('GET', repository_path(owner, program))
        result['repository'] = repository['full_name']
        result['reported_permissions'] = repository.get('permissions', {})
    return result


def list_programs(client, owner, topic='zog-project'):
    component(owner)
    result, page = [], 1
    while True:
        batch = client.request('GET', '/user/repos?per_page=100&page=%s&affiliation=owner,collaborator,organization_member' % page)
        for repository in batch:
            if repository['owner']['login'].lower() == owner.lower() and topic in repository.get('topics', []):
                result.append({'name': repository['name'], 'private': repository['private'],
                               'url': repository['html_url']})
        if len(batch) < 100:
            return sorted(result, key=lambda item: item['name'])
        page += 1


def create_program(client, owner, program, topic='zog-project'):
    path = repository_path(owner, program)
    try:
        existing = client.request('GET', path)
    except ShareError as error:
        if error.code != 'not-found':
            raise
    else:
        if topic not in existing.get('topics', []):
            client.request('PUT', path + '/topics',
                           {'names': existing.get('topics', []) + [topic]})
        return {'created': False, 'repository': existing['full_name'],
                'private': existing['private'], 'url': existing['html_url'],
                'topic_present': True}
    user = client.request('GET', '/user')
    if user['login'].lower() == owner.lower():
        endpoint = '/user/repos'
    else:
        account = client.request('GET', '/users/' + component(owner))
        if account.get('type') != 'Organization':
            raise ShareError('configuration', 'Owner must be the authenticated user or an organization.')
        endpoint = '/orgs/' + owner + '/repos'
    client.request('POST', endpoint, {'name': program, 'private': True, 'auto_init': True,
                                     'description': 'Zog program: ' + program})
    try:
        repository = client.request('GET', path)
        client.request('PUT', path + '/topics', {'names': [topic]})
    except ShareError:
        raise ShareError('partial', 'Repository creation succeeded; access/topic setup incomplete. Inspect it before retrying.',
                         'published') from None
    return {'created': True, 'repository': repository['full_name'], 'private': repository['private'],
            'url': repository['html_url'], 'topic_present': True}


def safe_path(value):
    parts = value.split('/')
    if not value or any(p in ('', '.', '..') or p.lower() in ('.git', '.version-share') for p in parts) or '\\' in value or '\0' in value:
        raise ShareError('unsafe-tree', 'Unsafe or reserved source path.')
    return parts


def retrieve(client, owner, program, destination, reference=None):
    """Create a fresh snapshot; reject existing paths, submodules and unsafe links."""
    path = repository_path(owner, program)
    destination = Path(destination).absolute()
    if os.path.lexists(destination):
        raise ShareError('conflict', 'Destination already exists; choose a fresh directory.')
    repository = client.request('GET', path)
    reference = reference or repository['default_branch']
    commit = client.request('GET', path + '/commits/' + urllib.parse.quote(reference, safe=''))
    sha = commit['sha']
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ShareError('remote', 'Invalid commit identifier.')
    tree = client.request('GET', path + '/git/trees/' + commit['commit']['tree']['sha'] + '?recursive=1')
    if tree.get('truncated'):
        raise ShareError('unsupported', 'Truncated source tree; no partial retrieval produced.')
    entries = tree['tree']
    if len(entries) > 10000:
        raise ShareError('unsupported', 'Source tree exceeds 10000 entries.')
    seen = set()
    for entry in entries:
        safe_path(entry['path'])
        if entry['path'] in seen:
            raise ShareError('unsafe-tree', 'Duplicate source path.')
        seen.add(entry['path'])
        if (entry['type'], entry['mode']) not in {('tree', '040000'), ('blob', '100644'), ('blob', '100755'), ('blob', '120000')}:
            raise ShareError('unsupported', 'Submodules or unsupported tree entries require a later pass.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.version-share-', dir=destination.parent))
    links = []
    total = 0
    try:
        for entry in entries:
            output = staging.joinpath(*safe_path(entry['path']))
            if entry['type'] == 'tree':
                output.mkdir(parents=True, exist_ok=True)
                continue
            blob = client.request('GET', path + '/git/blobs/' + entry['sha'])
            if blob.get('encoding') != 'base64':
                raise ShareError('remote', 'Unsupported blob encoding.')
            try:
                content = base64.b64decode(''.join(blob['content'].split()), validate=True)
            except (ValueError, TypeError):
                raise ShareError('remote', 'Invalid blob encoding.') from None
            actual = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
            if actual != entry['sha']:
                raise ShareError('integrity', 'Downloaded blob does not match Git object identifier.')
            total += len(content)
            if total > 128 * 1024 * 1024:
                raise ShareError('unsupported', 'Source snapshot exceeds 128 MiB.')
            output.parent.mkdir(parents=True, exist_ok=True)
            if entry['mode'] == '120000':
                try:
                    target = content.decode('utf-8')
                except UnicodeError:
                    raise ShareError('unsafe-tree', 'Non-UTF-8 symbolic link target.') from None
                if not target or '\0' in target or '\\' in target or Path(target).is_absolute():
                    raise ShareError('unsafe-tree', 'Unsafe symbolic link target.')
                links.append((output, target))
            else:
                output.write_bytes(content)
                output.chmod(0o755 if entry['mode'] == '100755' else 0o644)
        for output, target in links:
            output.symlink_to(target)
        for output, target in links:
            try:
                output.resolve().relative_to(staging)
            except (ValueError, RuntimeError):
                raise ShareError('unsafe-tree', 'Symbolic link escapes source tree or forms a cycle.') from None
        metadata = {'schema': 1, 'repository': repository['full_name'], 'repository_id': repository['id'],
                    'requested_reference': reference, 'commit': sha, 'destination': str(destination),
                    'files': {e['path']: {'sha': e['sha'], 'mode': e['mode']} for e in entries if e['type'] == 'blob'}}
        (staging / '.version-share').mkdir()
        (staging / '.version-share' / 'baseline.json').write_text(json.dumps(metadata, indent=2) + '\n')
        # Exclusive reservation prevents replacement of a concurrently created directory.
        destination.mkdir()
        try:
            os.replace(staging, destination)
        except BaseException:
            destination.rmdir()
            raise
        return metadata
    finally:
        if staging.exists():
            shutil.rmtree(staging)
