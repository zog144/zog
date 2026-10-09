#!/usr/bin/env python3
"""Destructive only within a NEW disposable application root; never targets a live installation.

Real npm and HTTP acceptance. Optional Work fixture explicitly substitutes OS identity
operations only; it must never be described as successful unprivileged acceptance.
"""
import argparse
import contextlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', SOURCE / 'tools/frontend-install.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def acceptance(args):
    root = args.application_root
    m.require(not root.exists(), 'Acceptance requires a NEW disposable root, never an existing installation')
    m.validate_root(root)
    args.source = str(SOURCE)
    realrun = subprocess.run

    def sandbox_run(*positional, **keywords):
        for name in ('user', 'group', 'extra_groups'):
            keywords.pop(name, None)
        return realrun(*positional, **keywords)

    with contextlib.ExitStack() as stack:
        if args.identity_fixture:
            print('IDENTITY FIXTURE: no OS uid/gid switching or ownership changes will be claimed.', flush=True)
            stack.enter_context(patch.object(m, 'identity', side_effect=[SimpleNamespace(pw_uid=30001, pw_gid=30001), SimpleNamespace(pw_uid=30002, pw_gid=30002)]))
            stack.enter_context(patch.object(m.os, 'chown'))
            stack.enter_context(patch.object(m.subprocess, 'run', side_effect=sandbox_run))
        with m.locked(root):
            first = m.prepare(root, args)
            m.build(root, first)
            m.verify(root, first)
    firstdir = root / 'releases' / first / 'dist'
    if not args.identity_fixture:
        # A real runtime process must fail to overwrite the installed entry point.
        runtime = m.identity(args.runtime_user)
        result = subprocess.run([sys.executable, '-c', 'from pathlib import Path; Path(__import__("sys").argv[1]).write_text("forbidden")', str(firstdir / 'index.html')],
                                user=runtime.pw_uid, group=runtime.pw_gid, extra_groups=[], capture_output=True)
        assert result.returncode != 0, 'Runtime overwrote installed output!'
        m.validate_release(root, first)
    second = 'f' * 32
    secondpath = root / 'releases' / second
    shutil.copytree(firstdir.parent, secondpath)
    for path in [secondpath, *secondpath.rglob('*')]:
        path.chmod(0o755 if path.is_dir() else 0o644)
    dist = secondpath / 'dist'
    inventory = m.load(dist / 'frontend-build.json')
    js = next(name for name in inventory['outputs'] if name.endswith('.js'))
    newjs = 'assets/index-rollbackfixture.js'
    (dist / js).rename(dist / newjs)
    (dist / newjs).write_text((dist / newjs).read_text() + '\n// isolated activation fixture\n')
    (dist / 'index.html').write_text((dist / 'index.html').read_text().replace(js, newjs))
    del inventory['outputs'][js]
    inventory['outputs'][newjs] = m.digest(dist / newjs)
    inventory['outputs']['index.html'] = m.digest(dist / 'index.html')
    m.atomic_json(dist / 'frontend-build.json', inventory)
    manifest = m.load(secondpath / 'installation.json')
    manifest.update(id=second, activation_fixture=True, outputs=m.regular_files(dist))
    m.atomic_json(secondpath / 'installation.json', manifest)
    for path in [secondpath, *secondpath.rglob('*')]:
        path.chmod(0o555 if path.is_dir() else 0o444)
    with (root / 'acceptance-http.log').open('w') as log:
        server = subprocess.Popen([sys.executable, str(SOURCE / 'tools/frontend-probe.py'), '--directory', str(firstdir), '--serve-installation', str(root)], stdout=subprocess.PIPE, stderr=log, text=True)
        try:
            url = server.stdout.readline().strip()
            assert url.startswith('http://127.0.0.1:')
            m.activate(root, first, url)
            m.activate(root, first, url)
            m.activate(root, second, url)
            previous = (root / 'selection.json').read_bytes()
            # Guaranteed content mismatch instead of assuming an unused network port.
            with patch.object(m, 'check_http', side_effect=lambda *a, **kw: realrun([sys.executable, str(SOURCE / 'tools/frontend-probe.py'), '--url', url, '--directory', str(dist)], check=True)):
                try:
                    m.activate(root, first, url)
                except m.InstallError:
                    pass
                else:
                    raise AssertionError('Expected failed HTTP content check')
            assert (root / 'selection.json').read_bytes() == previous
            m.check_http(url, manifest, dist, firstdir)
            m.activate(root, first, url)
            print(json.dumps({'result': 'passed', 'source_revision': args.source_revision, 'release': first,
                              'identity_execution': 'fixture-only' if args.identity_fixture else 'real-unprivileged',
                              'checks': ['clean-lockfile-build', 'tests-and-notices', 'http-activation-repeat', 'retained-assets', 'failed-http-restoration', 'explicit-rollback'],
                              'second_release': 'synthetic activation fixture, not a second source build'}))
        finally:
            server.terminate()
            server.wait(timeout=10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--application-root', type=Path, required=True)
    parser.add_argument('--source-revision', required=True)
    parser.add_argument('--node', required=True)
    parser.add_argument('--npm', required=True)
    parser.add_argument('--build-user', required=True)
    parser.add_argument('--runtime-user', required=True)
    parser.add_argument('--identity-fixture', action='store_true')
    acceptance(parser.parse_args())
