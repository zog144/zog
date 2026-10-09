"""Source-controlled handoff metadata, pinned dependencies and GitHub releases."""
import base64
import json
from pathlib import Path
import re
from urllib.parse import quote
from .core import ShareError, repository_path
from .publication import baseline, get_ref, ref_name
from .workspace import guard_secret, read_json, save_json, state_directory, object_hash, snapshot, manifest

HANDOFF_FILE = 'version-share-handoff.json'


def dependency(value):
    try:
        repository, commit = value.split('=', 1)
        owner, program = repository.split('/')
        repository_path(owner, program)
        if not re.fullmatch('[0-9a-f]{40}', commit):
            raise ValueError()
    except (ValueError, AttributeError):
        raise ShareError('configuration', 'Dependency must be OWNER/PROGRAM=FULL_COMMIT.') from None
    return {'repository': repository, 'commit': commit}


def write_handoff(client, directory, notes_file, test_results_file=None, dependencies=(), limitations=()):
    value, _ = baseline(client, directory)
    notes = Path(notes_file).read_text()
    tests = read_json(test_results_file) if test_results_file else []
    if not isinstance(tests, list) or any(not isinstance(t, dict) or set(t) != {'command', 'result'} or
                                        not all(isinstance(x, str) for x in t.values()) for t in tests):
        raise ShareError('configuration', 'Test results must be a JSON array of {command, result} strings.')
    pins = [dependency(item) for item in dependencies]
    if len({p['repository'] for p in pins}) != len(pins):
        raise ShareError('configuration', 'Duplicate dependency repository.')
    for pin in pins:
        path = repository_path(*pin['repository'].split('/'))
        result = client.request('GET', path + '/commits/' + pin['commit'])
        if result['sha'] != pin['commit']:
            raise ShareError('integrity', 'Dependency did not resolve to the requested commit.')
    document = {'schema': 1, 'repository': value['repository'], 'notes': notes,
                'tests': [dict(t, origin='caller-reported') for t in tests],
                'dependencies': pins, 'limitations': list(limitations)}
    provenance = state_directory(directory) / 'import.json'
    if provenance.exists():
        imported = read_json(provenance)
        document['import'] = {key: imported[key] for key in ('archive_name', 'archive_sha256', 'source_root', 'excluded')}
    guard_secret(json.dumps(document).encode(), client._token)
    target = Path(directory) / HANDOFF_FILE
    if target.is_symlink():
        raise ShareError('unsafe-tree', 'Handoff metadata cannot be a symbolic link.')
    save_json(target, document)
    return document


def read_remote_handoff(client, path, commit):
    result = client.request('GET', path + '/contents/' + HANDOFF_FILE + '?ref=' + commit)
    if result.get('encoding') != 'base64':
        raise ShareError('remote', 'Unsupported handoff encoding.')
    try:
        content = base64.b64decode(''.join(result['content'].split()), validate=True)
        if object_hash('blob', content) != result['sha']:
            raise ShareError('integrity', 'Handoff blob checksum mismatch.')
        document = json.loads(content)
    except (ValueError, TypeError):
        raise ShareError('remote', 'Invalid handoff metadata.') from None
    if not isinstance(document, dict) or document.get('schema') != 1 or not isinstance(document.get('notes'), str):
        raise ShareError('configuration', 'Unsupported handoff metadata schema.')
    return document


def create_release(client, owner, program, version):
    """Re-running reconciles by the existing tag; never edits an existing release."""
    ref_name(version)
    path = repository_path(owner, program)
    tag = 'handoffs/' + version
    commit = get_ref(client, path, 'tags/' + tag)
    if commit is None:
        raise ShareError('not-found', 'Publish the named handoff before creating its release.')
    document = read_remote_handoff(client, path, commit)
    body = document['notes'].rstrip() + '\n\nCommit: `' + commit + '`\n\n'
    body += 'Handoff metadata (test results are caller-reported):\n```json\n' + json.dumps(document, indent=2) + '\n```\n'
    guard_secret(body.encode(), client._token)
    endpoint = path + '/releases/tags/' + quote(tag, safe='')
    try:
        release = client.request('GET', endpoint)
    except ShareError as error:
        if error.code != 'not-found':
            raise
        try:
            release = client.request('POST', path + '/releases',
                                     {'tag_name': tag, 'target_commitish': commit, 'name': version,
                                      'body': body, 'draft': False, 'prerelease': False, 'make_latest': 'false'})
        except ShareError as creation_error:
            # Read-after-error reconciles a lost accepted response or simultaneous creation.
            try:
                release = client.request('GET', endpoint)
            except ShareError as inspection_error:
                if creation_error.outcome == 'not-published' and inspection_error.code == 'not-found':
                    raise creation_error
                raise ShareError('uncertain', 'Release outcome needs inspection; rerun release with this same handoff name.', 'uncertain') from None
    if release['tag_name'] != tag or release.get('body') != body or release.get('draft'):
        raise ShareError('conflict', 'An existing release has different metadata; it was not modified.')
    if get_ref(client, path, 'tags/' + tag) != commit:
        raise ShareError('uncertain', 'Handoff tag moved externally while creating the release.', 'uncertain')
    return {'repository': owner + '/' + program, 'version': version, 'commit': commit,
            'url': release['html_url'], 'zip_url': release['zipball_url'], 'tar_url': release['tarball_url'],
            'outcome': 'published'}


def retrieve_dependencies(client, directory, destination):
    from .transfer import retrieve_archive
    document = read_json(Path(directory) / HANDOFF_FILE)
    destination = Path(destination)
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        raise ShareError('conflict', 'Dependency destination must be a directory.')
    pins = [dependency(p['repository'] + '=' + p['commit']) for p in document.get('dependencies', [])]
    if len({p['repository'] for p in pins}) != len(pins):
        raise ShareError('configuration', 'Duplicate dependency repository.')
    # Each result is independently retrievable by its recorded pin if a later transfer fails.
    destination.mkdir(parents=True, exist_ok=True)
    results = []
    for pin in pins:
        owner, program = pin['repository'].split('/')
        target = destination / owner / program
        if target.is_symlink():
            raise ShareError('conflict', 'Dependency destination cannot be a symbolic link.')
        if target.exists():
            existing = read_json(state_directory(target) / 'baseline.json')
            files, _ = snapshot(target, client._token)
            if (existing.get('repository') != pin['repository'] or existing.get('commit') != pin['commit'] or
                    existing.get('files') != manifest(files)):
                raise ShareError('conflict', 'Existing dependency differs from its pin or has local changes.')
            results.append(existing)
        else:
            results.append(retrieve_archive(client, owner, program, target, pin['commit']))
    return {'dependencies': results, 'compatibility': 'Pins specify exact versions; compatibility is not inferred.'}


def project_index(client, owner):
    from .core import list_programs
    result = []
    for program in list_programs(client, owner):
        path = repository_path(owner, program['name'])
        repository = client.request('GET', path)
        commit = client.request('GET', path + '/commits/' + quote(repository['default_branch'], safe=''))['sha']
        result.append({'repository': repository['full_name'], 'default_branch': repository['default_branch'], 'commit': commit})
    return {'schema': 1, 'programs': result, 'compatibility': 'Discovery snapshot only; these versions are not asserted to be tested together.'}
