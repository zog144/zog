"""Same-origin frontend delivery for first-use and small-host deployments."""
import json
import re
import mimetypes
from pathlib import Path
from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.views.decorators.http import require_GET


def _frontend_roots():
    """Read one atomic selection snapshot. Retained sets serve only hashed assets."""
    installation = getattr(settings, 'STATION_ACCESS_FRONTEND_INSTALLATION', '')
    if not installation:
        return [Path(settings.STATION_ACCESS_FRONTEND_DIRECTORY).resolve()]
    base = Path(installation).resolve()
    try:
        selection = base / 'selection.json'
        if selection.is_symlink() or selection.stat().st_size > 1024 * 1024:
            raise ValueError()
        data = json.loads(selection.read_text())
        identifiers = data['retained']
        if (data['schema'] != 1 or not isinstance(identifiers, list) or not identifiers
                or identifiers[0] != data['active'] or len(set(identifiers)) != len(identifiers)):
            raise ValueError()
        roots = []
        for identifier in identifiers:
            if not isinstance(identifier, str) or not re.fullmatch('[a-f0-9]{32}', identifier):
                raise ValueError()
            path = base / 'releases' / identifier / 'dist'
            if path.resolve() != path or not path.is_dir():
                raise ValueError()
            roots.append(path)
        return roots
    except (OSError, ValueError, KeyError, TypeError):
        raise Http404('No valid frontend selection; verify and activate an installation.') from None


def _frontend_file(relative, retained=False):
    roots = _frontend_roots()
    for root in roots if retained else roots[:1]:
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            continue
        response = FileResponse(path.open('rb'), content_type=mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        response['X-Content-Type-Options'] = 'nosniff'
        return response
    raise Http404('Frontend file not found; build and activate the complete frontend')


@require_GET
def portal(request, route=''):
    response = _frontend_file('index.html')
    response['Cache-Control'] = 'no-store'
    return response


@require_GET
def asset(request, filename):
    if not re.fullmatch(r'[A-Za-z0-9_-]+-[A-Za-z0-9_-]+\.(?:js|css|txt)', filename):
        raise Http404('Unknown hashed frontend asset')
    response = _frontend_file('assets/' + filename, retained=True)
    if response['Content-Type'] == 'text/plain':
        response['Content-Type'] = 'text/plain; charset=utf-8'
    response['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response


@require_GET
def build_inventory(request):
    """Fixed public build evidence, independent of authentication and private state."""
    response = _frontend_file('frontend-build.json')
    response['Content-Type'] = 'application/json'
    response['Cache-Control'] = 'no-store'
    return response


@require_GET
def licenses(request):
    """Serve only the hashed, inventoried notice asset as inert plain text."""
    import hashlib
    import json
    import re
    root = _frontend_roots()[0]
    try:
        manifest_path = root / 'frontend-build.json'
        if manifest_path.is_symlink() or manifest_path.stat().st_size > 1024 * 1024:
            raise ValueError()
        manifest = json.loads(manifest_path.read_text())
        name = manifest['licenses']
        if not isinstance(name, str) or not re.fullmatch(r'assets/LICENSES-[a-f0-9]{12}\.txt', name):
            raise ValueError()
        notice_path = (root / name).resolve()
        if not notice_path.is_relative_to(root) or notice_path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError()
        data = notice_path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != manifest['outputs'][name] or name != 'assets/LICENSES-' + digest[:12] + '.txt':
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError):
        raise Http404('Frontend license evidence unavailable; rebuild and install the complete frontend.') from None
    response = HttpResponse(data, content_type='text/plain; charset=utf-8')
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    response['Cache-Control'] = 'no-store'
    return response
