"""Single-parent publication with durable, content-bound retry records."""
import base64
from datetime import datetime, timezone
from pathlib import Path
from functools import wraps
import re
from urllib.parse import quote
import uuid
from .core import ShareError, repository_path, safe_path
from .workspace import (changes, guard_secret, ignored, locked, manifest, object_hash,
                        read_json, save_json, snapshot, state_directory)


def ref_name(name):
    if (not name or name.startswith(('/', '-')) or name.endswith(('/', '.')) or
            '..' in name or '@{' in name or re.search(r'[\x00-\x20\x7f~^:?*\[\\]', name) or
            any(not part or part.startswith('.') or part.endswith('.lock') for part in name.split('/'))):
        raise ShareError('configuration', 'Invalid branch or version name.')
    return name


def remote_manifest(client, path, reference):
    commit = client.request('GET', path + '/commits/' + quote(reference, safe=''))
    tree = client.request('GET', path + '/git/trees/' + commit['commit']['tree']['sha'] + '?recursive=1')
    if tree.get('truncated'):
        raise ShareError('unsupported', 'Truncated remote source tree.')
    files = {}
    for item in tree['tree']:
        if item['type'] == 'tree':
            continue
        if item['type'] != 'blob' or item['mode'] not in ('100644', '100755', '120000'):
            raise ShareError('unsupported', 'Unsupported remote source entry.')
        safe_path(item['path'])
        files[item['path']] = {'sha': item['sha'], 'mode': item['mode']}
    return commit['sha'], files


def baseline(client, directory):
    value = read_json(state_directory(directory) / 'baseline.json')
    owner, program = value['repository'].split('/')
    path = repository_path(owner, program)
    if 'files' not in value:
        _, value['files'] = remote_manifest(client, path, value['commit'])
    return value, path


def status(client, directory):
    value, _ = baseline(client, directory)
    files, excluded = snapshot(directory, client._token)
    state = state_directory(directory)
    pending = read_json(state / 'publication.json') if (state / 'publication.json').exists() else None
    return {'repository': value['repository'], 'baseline': value['commit'],
            'changes': changes(value['files'], manifest(files)), 'excluded': excluded,
            'publication': None if not pending else {key: pending.get(key) for key in ('id', 'phase', 'commit', 'branch', 'version')}}


def compare(client, owner, program, before, after):
    path = repository_path(owner, program)
    first, old = remote_manifest(client, path, before)
    second, new = remote_manifest(client, path, after)
    return {'before': first, 'after': second, 'changes': changes(old, new)}


def get_ref(client, path, ref):
    try:
        result = client.request('GET', path + '/git/ref/' + quote(ref, safe='/'))
    except ShareError as error:
        if error.code == 'not-found':
            return None
        raise
    if result['object']['type'] != 'commit':
        raise ShareError('conflict', 'Expected a direct commit reference.')
    return result['object']['sha']


def tree_hash(files):
    root = {}
    for path, item in files.items():
        node = root
        parts = path.split('/')
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = (item['mode'], item['sha'])
    def digest(node):
        result = []
        for name, value in node.items():
            mode, sha = ('40000', digest(value)) if isinstance(value, dict) else value
            result.append((name.encode() + (b'/' if mode == '40000' else b''),
                           mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(sha)))
        return object_hash('tree', b''.join(value for _, value in sorted(result)))
    return digest(root)


def upload_tree(client, path, operation):
    entries = []
    uploaded_blobs = set()
    for name, item in operation['files'].items():
        content = base64.b64decode(item['content'])
        entry = {'path': name, 'mode': item['mode'], 'type': 'blob'}
        try:
            entry['content'] = content.decode('utf-8')
        except UnicodeError:
            if item['sha'] not in uploaded_blobs:
                result = client.request('POST', path + '/git/blobs', {'encoding': 'base64', 'content': item['content']})
                if result['sha'] != item['sha']:
                    raise ShareError('integrity', 'Uploaded blob identifier mismatch.')
                uploaded_blobs.add(item['sha'])
            entry['sha'] = item['sha']
        entries.append(entry)
    result = client.request('POST', path + '/git/trees', {'tree': entries})
    expected = tree_hash(operation['files'])
    if result['sha'] != expected:
        raise ShareError('integrity', 'Uploaded tree identifier mismatch.')
    return expected


def result_for(operation):
    return {'outcome': 'published', 'publication_id': operation['id'],
            'repository': operation['repository'], 'branch': operation['branch'],
            'commit': operation['commit'], 'version': operation['version'],
            'url': 'https://github.com/' + operation['repository'] + '/commit/' + operation['commit'],
            'changes': operation['changes'], 'excluded': operation['excluded']}


def contains(client, path, ancestor, head):
    if ancestor == head:
        return True
    if head is None:
        return False
    result = client.request('GET', path + '/compare/' + ancestor + '...' + head + '?per_page=1')
    return result['status'] in ('ahead', 'identical')


def finish(client, directory, state, operation, path):
    """Continue only the frozen source and publication parameters recorded on disk."""
    record = state / 'publication.json'
    if operation['phase'] == 'complete':
        return result_for(operation)
    # Recheck frozen bytes with the current credential before any upload (including retries).
    guard_secret(operation['message'].encode(), client._token)
    for name, item in operation['files'].items():
        guard_secret(name.encode() + b'\0' + base64.b64decode(item['content']), client._token)
    repository = client.request('GET', path)
    if repository['id'] != operation['repository_id']:
        raise ShareError('conflict', 'Repository identity changed; refusing publication.')
    branch_ref = 'heads/' + operation['branch']
    # A handoff name is never replaced by this program.
    tag_ref = 'tags/handoffs/' + operation['version'] if operation['version'] else None
    if tag_ref and operation['phase'] in ('prepared', 'objects-ready'):
        existing = get_ref(client, path, tag_ref)
        if existing and existing != operation.get('commit'):
            raise ShareError('conflict', 'Handoff name already identifies another commit.',
                             'published' if operation['phase'] in ('branch-published', 'complete') else 'not-published')
    if operation['phase'] in ('prepared', 'objects-ready'):
        head = get_ref(client, path, branch_ref)
        if head != operation['expected_head']:
            raise ShareError('conflict', 'Destination branch advanced; local source is preserved. Publish to a new branch.', 'not-published')
    if operation['phase'] == 'prepared':
        tree = upload_tree(client, path, operation)
        body = {'tree': tree, 'parents': [operation['baseline']], 'message': operation['message'],
                'author': operation['identity'], 'committer': operation['identity']}
        # Identical tree, parents, message, author and timestamp yield the same object on retry.
        commit = client.request('POST', path + '/git/commits', body)
        if commit['tree']['sha'] != tree or [p['sha'] for p in commit['parents']] != [operation['baseline']]:
            raise ShareError('integrity', 'Commit response does not match prepared source.')
        operation['commit'] = commit['sha']
        operation['phase'] = 'objects-ready'
        save_json(record, operation)
    if operation['phase'] == 'objects-ready':
        head = get_ref(client, path, branch_ref)
        if head != operation['expected_head']:
            raise ShareError('conflict', 'Destination branch changed before publication.', 'not-published')
        operation['phase'] = 'reference-attempted'
        save_json(record, operation)
        return publish_reference(client, directory, state, operation, path)
    if operation['phase'] == 'reference-attempted':
        head = get_ref(client, path, branch_ref)
        if contains(client, path, operation['commit'], head):
            operation['phase'] = 'branch-published'
            save_json(record, operation)
        elif head == operation['expected_head']:
            return publish_reference(client, directory, state, operation, path)
        else:
            raise ShareError('uncertain', 'Branch changed after an attempted publication; inspect remote history before taking further action.', 'uncertain')
    if operation['phase'] == 'branch-published':
        if tag_ref:
            current = get_ref(client, path, tag_ref)
            if current is None:
                try:
                    client.request('POST', path + '/git/refs', {'ref': 'refs/' + tag_ref, 'sha': operation['commit']})
                except ShareError:
                    # The next resume checks this exact immutable name before creating anything.
                    raise ShareError('partial', 'Branch published; handoff creation needs reconciliation. Run resume.', 'published') from None
                current = get_ref(client, path, tag_ref)
            if current != operation['commit']:
                raise ShareError('partial', 'Branch published; handoff name belongs to another commit.', 'published')
        baseline_value = read_json(state / 'baseline.json')
        baseline_value.update({'commit': operation['commit'], 'files': manifest(operation['files']),
                               'requested_reference': operation['branch']})
        save_json(state / 'baseline.json', baseline_value)
        receipt = {'id': operation['id'], 'branch': operation['branch'], 'summary': operation['summary'],
                   'version': operation['version'], 'result': result_for(operation)}
        save_json(state / ('receipt-' + operation['id'] + '.json'), receipt)
        operation['phase'] = 'complete'
        save_json(record, operation)
        return result_for(operation)
    raise ShareError('local', 'Unknown publication phase.')


def publish_reference(client, directory, state, operation, path):
    try:
        if operation['expected_head'] is None:
            client.request('POST', path + '/git/refs', {'ref': 'refs/heads/' + operation['branch'], 'sha': operation['commit']})
        else:
            client.request('PATCH', path + '/git/refs/heads/' + quote(operation['branch'], safe='/'),
                           {'sha': operation['commit'], 'force': False})
    except ShareError as error:
        if error.outcome == 'not-published':
            operation['phase'] = 'objects-ready'
            save_json(state / 'publication.json', operation)
            raise ShareError(error.code, str(error), 'not-published') from None
        raise ShareError('uncertain', 'Publication response was lost or ambiguous. Run resume to inspect the recorded commit.', 'uncertain') from None
    operation['phase'] = 'branch-published'
    save_json(state / 'publication.json', operation)
    return finish(client, directory, state, operation, path)


def publication_errors(function):
    @wraps(function)
    def call(client, directory, *args, **kwargs):
        try:
            return function(client, directory, *args, **kwargs)
        except (OSError, ShareError) as error:
            outcome = 'not-published'
            try:
                record = state_directory(directory) / 'publication.json'
                operation = read_json(record) if record.exists() else {}
                phase = operation.get('phase')
                requested_id = kwargs.get('publication_id', args[3] if len(args) > 3 else None)
                if phase == 'branch-published' or (phase == 'complete' and
                        (function.__name__ == 'resume' or requested_id == operation.get('id'))):
                    outcome = 'published'
                elif phase == 'reference-attempted':
                    outcome = 'uncertain'
            except (OSError, ShareError):
                outcome = 'uncertain'
            if isinstance(error, ShareError):
                if error.outcome in ('published', 'uncertain'):
                    outcome = error.outcome
                raise ShareError(error.code, str(error), outcome) from None
            raise ShareError('local', 'Local state write failed. Restore storage and run resume before publishing again.', outcome) from None
    return call

@publication_errors
def publish(client, directory, branch, message, version=None, publication_id=None):
    ref_name(branch)
    if version:
        ref_name(version)
    if not message or not message.strip():
        raise ShareError('configuration', 'A nonempty commit message is required.')
    guard_secret((message + branch + (version or '')).encode(), client._token)
    publication_id = publication_id or str(uuid.uuid4())
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', publication_id):
        raise ShareError('configuration', 'Invalid publication identifier.')
    with locked(directory) as state:
        record = state / 'publication.json'
        receipt_path = state / ('receipt-' + publication_id + '.json')
        if receipt_path.exists():
            receipt = read_json(receipt_path)
            if (branch, message, version) != (receipt['branch'], receipt['summary'], receipt['version']):
                raise ShareError('conflict', 'Publication identifier is already bound to different parameters.')
            return receipt['result']
        if (state / ('abandoned-' + publication_id + '.json')).exists():
            raise ShareError('conflict', 'Publication identifier was abandoned; use a new identifier.')
        previous = read_json(record) if record.exists() else None
        if previous and previous['id'] == publication_id:
            if (branch, message, version) != (previous['branch'], previous['summary'], previous['version']):
                raise ShareError('conflict', 'Publication identifier is already bound to different parameters.')
            return finish(client, directory, state, previous, repository_path(*previous['repository'].split('/')))
        if previous and previous['phase'] != 'complete':
            raise ShareError('conflict', 'A publication is pending. Use resume, or abandon before publishing a new branch.')
        value, path = baseline(client, directory)
        files, excluded = snapshot(directory, client._token)
        if any(ignored(name) for name in value['files']):
            raise ShareError('secret', 'Baseline contains excluded paths; refusing silent deletion. Clean the repository separately.', 'not-published')
        delta = changes(value['files'], manifest(files))
        head = get_ref(client, path, 'heads/' + branch)
        if head is not None and head != value['commit']:
            raise ShareError('conflict', 'Destination branch advanced; choose a new branch or retrieve its current version.', 'not-published')
        if version and get_ref(client, path, 'tags/handoffs/' + version) is not None:
            raise ShareError('conflict', 'Handoff name already exists; names cannot be reused.', 'not-published')
        user = client.request('GET', '/user')
        identity = {'name': user['login'], 'email': str(user['id']) + '+' + user['login'] + '@users.noreply.github.com',
                    'date': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
        operation = {'schema': 1, 'id': publication_id, 'repository': value['repository'],
                     'repository_id': value['repository_id'], 'baseline': value['commit'],
                     'expected_head': head, 'branch': branch, 'version': version, 'identity': identity,
                     'summary': message, 'message': message.rstrip() + '\n\nVersion-Share-Publication: ' + publication_id + '\n',
                     'files': files, 'excluded': excluded, 'changes': delta, 'phase': 'prepared'}
        save_json(record, operation)
        return finish(client, directory, state, operation, path)


@publication_errors
def resume(client, directory):
    with locked(directory) as state:
        operation = read_json(state / 'publication.json')
        return finish(client, directory, state, operation, repository_path(*operation['repository'].split('/')))


def abandon(directory):
    """Discard local preparation only when no reference may have been changed."""
    with locked(directory) as state:
        operation = read_json(state / 'publication.json')
        if operation['phase'] not in ('prepared', 'objects-ready'):
            raise ShareError('conflict', 'Cannot abandon an attempted or completed publication; reconcile it with resume.')
        operation['phase'] = 'abandoned'
        save_json(state / ('abandoned-' + operation['id'] + '.json'), operation)
        (state / 'publication.json').unlink()
        return {'abandoned': operation['id'], 'local_source_preserved': True}


def list_versions(client, owner, program):
    path = repository_path(owner, program)
    result, page = [], 1
    while True:
        batch = client.request('GET', path + '/tags?per_page=100&page=' + str(page))
        for tag in batch:
            if tag['name'].startswith('handoffs/'):
                result.append({'name': tag['name'][9:], 'reference': tag['name'], 'commit': tag['commit']['sha']})
        if len(batch) < 100:
            return result
        page += 1
