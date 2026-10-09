# Data only; parsed with ast.literal_eval.
{'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/zog144-host-identify-4ea771766df606307769b5f56e22d06296440984\n'
            "python3 - <<'ZOG_BUILD'\n"
            'import importlib,os,pathlib,sys,tomllib\n'
            "p=tomllib.loads(pathlib.Path('pyproject.toml').read_text())['build-system']\n"
            'from packaging.requirements import Requirement\n'
            'from importlib.metadata import version\n'
            'def check(items):\n'
            ' for text in items:\n'
            '  r=Requirement(text)\n'
            "  if r.marker and not r.marker.evaluate({'extra':''}): continue\n"
            "  assert version(r.name) in r.specifier, ('unsatisfied build requirement',text)\n"
            "check(p['requires'])\n"
            "check(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project'].get('dependencies',[]))\n"
            "for entry in reversed(p.get('backend-path',[])):\n"
            ' path=pathlib.Path(entry).resolve()\n'
            ' assert path.is_relative_to(pathlib.Path.cwd())\n'
            ' sys.path.insert(0,str(path))\n'
            "backend=importlib.import_module(p['build-backend'])\n"
            "extra=getattr(backend,'get_requires_for_build_wheel',lambda config: [])({})\n"
            'check(extra)\n'
            "pathlib.Path('dist').mkdir(exist_ok=True)\n"
            "print('ZOG_SOURCE_WHEEL',backend.build_wheel(str(pathlib.Path('dist').resolve()),{}),flush=True)\n"
            'ZOG_BUILD\n']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/zog144-host-identify-4ea771766df606307769b5f56e22d06296440984\n'
           "python3 - <<'ZOG_TEST'\n"
           'import pathlib,zipfile,tempfile,sys,email\n'
           "wheels=list(pathlib.Path('dist').glob('*.whl'));assert len(wheels)==1\n"
           "with tempfile.TemporaryDirectory(prefix='zog-package-test-') as tmp:\n"
           ' with zipfile.ZipFile(wheels[0]) as z:\n'
           '  assert z.testzip() is None\n'
           "  assert all(not n.startswith('/') and '..' not in pathlib.PurePosixPath(n).parts for "
           'n in z.namelist())\n'
           '  z.extractall(tmp)\n'
           ' sys.path.insert(0,tmp)\n'
           " exec('import json, stat, tempfile, time, uuid\\nfrom pathlib import Path\\nfrom "
           'importlib.metadata import version, requires\\nfrom packaging.requirements import '
           'Requirement\\nfrom host_identify import initialization, signatures, managed\\nfrom '
           "http_message_signatures import InvalidSignature\\nassert version(\\'host-identify\\') "
           "== \\'0.3.4\\'\\nfor raw in requires(\\'host-identify\\') or []:\\n    req = "
           'Requirement(raw)\\n    if req.marker is None or '
           "req.marker.evaluate({\\'extra\\':\\'\\'}):\\n        assert version(req.name) in "
           'req.specifier, raw\\nwith '
           "tempfile.TemporaryDirectory(prefix=\\'zog-identity-check-\\') as scratch:\\n    root = "
           "Path(scratch)/\\'identity\\'; root.mkdir(mode=0o700)\\n    auth = "
           "{\\'schema\\':1,\\'kind\\':\\'zog-identity-initialization\\',\\'authorization_id\\':str(uuid.uuid4()),\\n            "
           "\\'installation_id\\':str(uuid.uuid4()),\\'state_volume_id\\':str(uuid.uuid4()),\\n            "
           "\\'identity_directory\\':str(root),\\'account_profile\\':\\'zog-host-accounts-v1\\',\\'expected_fingerprint\\':None}\\n    "
           'receipt = initialization.prepare(root, auth)\\n    before = {p.name:p.read_bytes() for '
           'p in root.iterdir()}\\n    assert initialization.prepare(root, auth) == receipt\\n    '
           'assert before == {p.name:p.read_bytes() for p in root.iterdir()}\\n    assert '
           'all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in root.iterdir())\\n    key = '
           'initialization.load_existing(root, receipt)\\n    assert '
           "signatures.fingerprint(key.public_key()) == receipt[\\'fingerprint\\']\\n    host = "
           'str(uuid.uuid4()); url = '
           "\\'https://registry.example.invalid/api/hosts/enrollment/\\'\\n    body = "
           'b\\\'{"fixture":"enrollment"}\\\'\\n    request = signatures.sign(url, body, key, '
           "host)\\n    nonce, expiry = signatures.verify(url, \\'POST\\', request.headers, body, "
           'key.public_key(), host)\\n    assert nonce and expiry.timestamp() > time.time()\\n    '
           "try:\\n        signatures.verify(url, \\'POST\\', request.headers, b\\'{}\\', "
           'key.public_key(), host)\\n    except (ValueError, InvalidSignature):\\n        '
           "pass\\n    else:\\n        raise AssertionError(\\'altered body accepted\\')\\n    now "
           '= int(time.time())\\n    expected = '
           "dict(iss=\\'https://station.example.invalid\\',aud=host,sub=str(uuid.uuid4()),\\n        "
           "fingerprint=receipt[\\'fingerprint\\'],installation_id=auth[\\'installation_id\\'],state_volume_id=auth[\\'state_volume_id\\'],\\n        "
           "registry_id=\\'fixture\\',challenge=str(uuid.uuid4()),previous=None,boot_id=str(uuid.uuid4()))\\n    "
           'claims = '
           "dict(expected,iat=now,exp=now+120,jti=str(uuid.uuid4()),epoch=1,checkpoint=str(uuid.uuid4()),operations=[\\'inspect\\'])\\n    "
           'envelope = managed.sign(claims,key,managed.SESSION_TYPE)\\n    assert '
           'managed.session(envelope,key.public_key(),expected) == claims\\n    try:\\n        '
           'managed.session(envelope,key.public_key(),dict(expected,challenge=str(uuid.uuid4())))\\n    '
           'except ValueError:\\n        pass\\n    else:\\n        raise '
           "AssertionError(\\'incorrect session binding accepted\\')\\n    "
           "(root/\\'identity.pem\\').unlink()\\n    try:\\n        "
           'initialization.load_existing(root, receipt)\\n    except '
           'initialization.IdentityStateError:\\n        pass\\n    else:\\n        raise '
           "AssertionError(\\'missing identity accepted\\')\\n    assert not "
           "(root/\\'identity.pem\\').exists()\\nprint(\\'ZOG_HOST_IDENTITY_INIT_SIGNATURE_SESSION_PASS\\')\\n')\n"
           'ZOG_TEST\n']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/zog144-host-identify-4ea771766df606307769b5f56e22d06296440984\n'
              'python3 -m installer --destdir="$DESTDIR" dist/*.whl\n']],
 'environment': {'PIP_NO_INDEX': '1', 'PYTHONNOUSERSITE': '1'}}
