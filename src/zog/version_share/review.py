"""Bounded, read-only comparison of two exact source snapshots."""
import base64
import difflib
from urllib.parse import quote
from .core import ShareError, repository_path
from .publication import remote_manifest
from .workspace import changes, object_hash

MAXIMUM_BLOB = 64 * 1024
MAXIMUM_LINES = 2000
MAXIMUM_PATCH = 256 * 1024


def read_blob(client, path, sha):
    blob = client.request('GET', path + '/git/blobs/' + sha)
    if blob.get('encoding') != 'base64' or not isinstance(blob.get('content'), str):
        raise ShareError('remote', 'Unsupported review blob encoding.')
    try:
        content = base64.b64decode(''.join(blob['content'].split()), validate=True)
    except ValueError:
        raise ShareError('remote', 'Invalid review blob encoding.') from None
    if object_hash('blob', content) != sha:
        raise ShareError('integrity', 'Review blob does not match the resolved source tree.')
    return content


def review(client, owner, program, before, after, maximum_files=20):
    if type(maximum_files) is not int or not 0 <= maximum_files <= 100:
        raise ShareError('configuration', 'maximum-files must be between 0 and 100.')
    path = repository_path(owner, program)
    first, old = remote_manifest(client, path, before)
    second, new = remote_manifest(client, path, after)
    difference = changes(old, new)
    base_url = 'https://github.com/' + owner + '/' + program
    records, attempted, remaining = [], 0, MAXIMUM_PATCH
    for kind in ('added', 'deleted', 'modified'):
        for name in difference[kind]:
            previous, current = old.get(name), new.get(name)
            record = {'path': name, 'change': kind, 'before': previous, 'after': current,
                      'before_url': base_url + '/blob/' + first + '/' + quote(name, safe='/') if previous else None,
                      'after_url': base_url + '/blob/' + second + '/' + quote(name, safe='/') if current else None}
            records.append(record)
            if previous and current and previous['sha'] == current['sha']:
                record['diff_status'] = 'mode-only'
                continue
            if attempted >= maximum_files or remaining <= 0:
                record['diff_status'] = 'omitted-budget'
                continue
            attempted += 1
            contents = [read_blob(client, path, entry['sha']) if entry else b''
                        for entry in (previous, current)]
            if any(len(content) > MAXIMUM_BLOB for content in contents):
                record['diff_status'] = 'omitted-size'
                continue
            try:
                if any(b'\0' in content for content in contents):
                    raise UnicodeError()
                texts = [content.decode('utf-8') for content in contents]
            except UnicodeError:
                record['diff_status'] = 'binary'
                continue
            lines = [text.splitlines(keepends=True) for text in texts]
            if any(len(value) > MAXIMUM_LINES for value in lines):
                record['diff_status'] = 'omitted-lines'
                continue
            patch = ''.join(line if line.endswith('\n') else line + '\n\\ No newline at end of file\n'
                            for line in difflib.unified_diff(*lines,
                                fromfile='a/' + name if previous else '/dev/null',
                                tofile='b/' + name if current else '/dev/null'))
            size = len(patch.encode('utf-8'))
            if size > remaining:
                record['diff_status'] = 'omitted-budget'
                continue
            remaining -= size
            record.update(diff_status='text', patch=patch)
    return {'repository': owner + '/' + program, 'before': first, 'after': second,
            'before_url': base_url + '/commit/' + first, 'after_url': base_url + '/commit/' + second,
            'comparison': 'endpoint-trees', 'counts': {key: len(value) for key, value in difference.items()},
            'files': records, 'complete_text_diffs': all(r['diff_status'] in ('text', 'mode-only') for r in records),
            'limits': {'maximum_files': maximum_files, 'maximum_blob_bytes': MAXIMUM_BLOB,
                       'maximum_lines': MAXIMUM_LINES, 'maximum_patch_bytes': MAXIMUM_PATCH}}
