#!/usr/bin/env python3
"""Bounded HTTP checks using station-access's real static views under Django/Waitress.

Isolates frontend serving from database, controller, authentication and cloud services.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler


def check(url, directory, retained=None):
    from html.parser import HTMLParser
    class References(HTMLParser):
        def __init__(self):
            super().__init__(); self.paths = []
        def handle_starttag(self, tag, attributes):
            data = dict(attributes)
            for name in ('src', 'href'):
                if data.get(name, '').startswith('/assets/'):
                    self.paths.append(data[name])
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('Health URL must be an HTTP(S) origin without credentials, path, query or fragment')
    if parsed.scheme == 'http' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('Plain HTTP health checks are restricted to loopback; use verified HTTPS remotely')
    opener = build_opener(NoRedirect)
    def get(path):
        with opener.open(url.rstrip('/') + path, timeout=10) as response:
            body = response.read(8 * 1024 * 1024 + 1)
            assert len(body) <= 8 * 1024 * 1024, 'Oversized serving response'
            assert response.status == 200, path
            return body, response.headers
    inventory = json.loads((directory / 'frontend-build.json').read_text())
    body, headers = get('/frontend-build.json')
    assert body == (directory / 'frontend-build.json').read_bytes(), 'Served build inventory differs from candidate'
    assert headers.get_content_type() == 'application/json'
    for route in ('/', '/workspaces', '/administration'):
        body, headers = get(route)
        assert body == (directory / 'index.html').read_bytes(), 'Client-side route returned a different entry point'
        assert headers.get_content_type() == 'text/html' and headers.get('Cache-Control') == 'no-store'
    references = References(); references.feed(body.decode())
    assert references.paths and ('/' + inventory['licenses']) in references.paths
    assert all(path[1:] in inventory['outputs'] for path in references.paths), 'HTML references missing output'
    for name, sha in inventory['outputs'].items():
        if name == 'index.html':
            continue
        body, headers = get('/' + name)
        assert hashlib.sha256(body).hexdigest() == sha, name
        expected = 'text/css' if name.endswith('.css') else 'text/plain' if name.endswith('.txt') else 'javascript' if name.endswith('.js') else None
        if expected == 'javascript':
            assert headers.get_content_type() in ('text/javascript', 'application/javascript'), name
        elif expected:
            assert headers.get_content_type() == expected, name
        assert headers.get('X-Content-Type-Options') == 'nosniff', name
    body, headers = get('/licenses/')
    assert body == (directory / inventory['licenses']).read_bytes()
    assert headers.get_content_type() == 'text/plain'
    assert headers.get('X-Content-Type-Options') == 'nosniff' and 'sandbox' in headers.get('Content-Security-Policy', '')
    if retained:
        old = json.loads((retained / 'frontend-build.json').read_text())
        for name, sha in old['outputs'].items():
            if name.startswith('assets/'):
                assert hashlib.sha256(get('/' + name)[0]).hexdigest() == sha, 'Retained asset unavailable: ' + name
    print('Django/Waitress entry, client routes, inventory, HTML references, output bytes/MIME, plaintext notices and retained assets passed.')


def serve(directory, application_root=None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
    from django.conf import settings
    settings.configure(DEBUG=False, SECRET_KEY='isolated-frontend-http-fixture', ALLOWED_HOSTS=['127.0.0.1', 'localhost'],
                       ROOT_URLCONF=__name__, MIDDLEWARE=[], INSTALLED_APPS=[],
                       STATION_ACCESS_FRONTEND_DIRECTORY=directory,
                       STATION_ACCESS_FRONTEND_INSTALLATION=application_root or '')
    from django.urls import path, re_path
    from zog.station_access.web import portal, asset, licenses, build_inventory
    global urlpatterns
    urlpatterns = [path('', portal), path('licenses/', licenses), path('frontend-build.json', build_inventory),
                   path('assets/<path:filename>', asset), re_path(r'^(?P<route>(?:workspaces|administration))/?$', portal)]
    from django.core.wsgi import get_wsgi_application
    from waitress import create_server
    server = create_server(get_wsgi_application(), host='127.0.0.1', port=0)
    threading.Thread(target=server.run, daemon=True).start()
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--retained-directory', type=Path)
    parser.add_argument('--url')
    parser.add_argument('--serve-installation', type=Path, help='Local acceptance server; prints origin and waits')
    args = parser.parse_args()
    if args.serve_installation:
        server = serve(args.directory, args.serve_installation)
        print('http://127.0.0.1:' + str(server.effective_port), flush=True)
        try:
            threading.Event().wait()
        finally:
            server.close()
    elif args.url:
        check(args.url, args.directory, args.retained_directory)
    else:
        server = serve(args.directory)
        try:
            check('http://127.0.0.1:' + str(server.effective_port), args.directory)
        finally:
            server.close()


if __name__ == '__main__':
    main()
