"""Fast snapshot retrieval with authenticated API-to-codeload redirect separation."""
import io
import os
from pathlib import Path
import http.client
import urllib.error
from urllib.parse import quote, urlsplit
import urllib.request
import zipfile
from .archives import MAXIMUM_ARCHIVE, install_snapshot, zip_files
from .core import ShareError, repository_path
from .publication import remote_manifest
from .workspace import manifest


def download_archive(client, path):
    url = 'https://api.github.com' + path
    headers = {'Authorization': 'Bearer ' + client._token, 'Accept': 'application/vnd.github+json',
               'User-Agent': 'version-share/0.3.0', 'X-GitHub-Api-Version': '2022-11-28'}
    for _ in range(4):
        request = urllib.request.Request(url, headers=headers)
        try:
            with client._opener.open(request, timeout=30) as response:
                content = response.read(MAXIMUM_ARCHIVE + 1)
            if len(content) > MAXIMUM_ARCHIVE:
                raise ShareError('unsupported', 'Archive download exceeds 64 MiB.')
            return content
        except urllib.error.HTTPError as error:
            if error.code not in (301, 302, 303, 307, 308):
                raise ShareError('remote', 'Archive download returned HTTP ' + str(error.code) + '.') from None
            location = error.headers.get('Location', '')
            parsed = urlsplit(location)
            try:
                port = parsed.port
            except ValueError:
                raise ShareError('unsafe-tree', 'Invalid archive redirect address.') from None
            if (parsed.scheme != 'https' or parsed.hostname != 'codeload.github.com' or
                    parsed.username or parsed.password or parsed.fragment or port not in (None, 443)):
                raise ShareError('unsafe-tree', 'Archive redirect was not an approved GitHub download host.')
            url = location
            # Private archive redirects are short-lived URLs; never forward the API token.
            headers = {'User-Agent': 'version-share/0.3.0'}
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            raise ShareError('network', 'Archive download failed; retry or use --transport blobs.') from None
    raise ShareError('remote', 'Archive redirect limit exceeded.')


def retrieve_archive(client, owner, program, destination, reference=None):
    if os.path.lexists(destination):
        raise ShareError('conflict', 'Destination exists; choose a fresh directory.')
    path = repository_path(owner, program)
    repository = client.request('GET', path)
    reference = reference or repository['default_branch']
    commit, expected = remote_manifest(client, path, reference)
    content = download_archive(client, path + '/zipball/' + commit)
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as package:
            roots = {i.filename.split('/')[0] for i in package.infolist()}
            if len(roots) != 1:
                raise ShareError('unsafe-tree', 'GitHub archive must contain one source root.')
            root = roots.pop()
        files, _ = zip_files(io.BytesIO(content), root)
    except zipfile.BadZipFile:
        raise ShareError('remote', 'GitHub returned an invalid ZIP archive.') from None
    if manifest(files) != expected:
        raise ShareError('integrity', 'Archive does not exactly match the pinned Git tree; no snapshot installed. Use --transport blobs for LFS/archive-attribute differences.')
    metadata = {'schema': 1, 'repository': repository['full_name'], 'repository_id': repository['id'],
                'requested_reference': reference, 'commit': commit, 'destination': str(Path(destination).absolute()),
                'files': expected}
    install_snapshot(files, destination, metadata)
    return metadata
