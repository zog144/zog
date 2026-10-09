# Data only; parsed with ast.literal_eval.
{'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/zog144-host-discover-eee9e574e8c139955da60b4b1bba4618c2912f48\n'
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
           'cd upstream/zog144-host-discover-eee9e574e8c139955da60b4b1bba4618c2912f48\n'
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
           ' exec("import json, tempfile, uuid\\nfrom pathlib import Path\\nfrom unittest.mock '
           'import patch\\nfrom importlib.metadata import version, requires\\nfrom '
           'packaging.requirements import Requirement\\nfrom host_identify import storage, '
           'signatures\\nfrom host_discover.daemon import announce\\nimport host_discover.beacon, '
           'host_discover.recovery, host_discover.supervisor\\nimport '
           'host_install.state_contract\\nfor name, expected in '
           "[('host-identify','0.3.4'),('host-install','0.4.3'),('host-discover','0.4.5')]:\\n    "
           'assert version(name) == expected\\n    for raw in requires(name) or []:\\n        req '
           '= Requirement(raw)\\n        if req.marker is None or '
           "req.marker.evaluate({'extra':''}):assert version(req.name) in req.specifier,raw\\nwith "
           "tempfile.TemporaryDirectory(prefix='zog-enrollment-check-') as scratch:\\n    "
           "root=Path(scratch)/'identity';root.mkdir(mode=0o700)\\n    "
           "shared=Path(scratch)/'credentials';shared.mkdir(mode=0o750)\\n    "
           "config={'server':'https://registry.example.invalid','identity_directory':str(root),'credential_directory':str(shared),'provider':'generic'}\\n    "
           'key=storage.load_key(root);fp=signatures.fingerprint(key.public_key());host=str(uuid.uuid4());sent=[]\\n    '
           'class Response:\\n        def '
           '__init__(self,value,status=200):self.value=value;self.status=status\\n        def '
           '__enter__(self):return self\\n        def __exit__(self,*args):pass\\n        def '
           'read(self,maximum):return json.dumps(self.value).encode()[:maximum]\\n    def '
           'open_request(request,**kwargs):\\n        sent.append(request)\\n        if '
           "len(sent)==1:return Response({'status':'pending','fingerprint':fp},202)\\n        if "
           'len(sent)==2:return '
           "Response({'status':'approved','fingerprint':fp,'host_id':host})\\n        return "
           "Response({'version':2,'host_id':host,'archive':None})\\n    with "
           "patch('urllib.request.OpenerDirector.open',side_effect=open_request):\\n        for _ "
           "in range(3):announce(config,{'version':1})\\n    assert len(sent)==3 and "
           "'/enrollment/' in sent[0].full_url\\n    assert f'/{host}/heartbeat/' in "
           "sent[2].full_url\\n    assert not any(request.has_header('Authorization') for request "
           'in sent)\\n    '
           "signatures.verify(sent[2].full_url,'POST',dict(sent[2].header_items()),sent[2].data,key.public_key(),host)\\n    "
           'assert '
           'json.loads((root/\'binding.json\').read_text())[\'host_id\']==host\\nprint(\'ZOG_HOST_ENROLLMENT_PENDING_APPROVED_HEARTBEAT_PASS\')\\nprint(\'ZOG_HOST_ENROLLMENT_INSTALLED_ACCEPTANCE_PASS\')\\n")\n'
           'ZOG_TEST\n']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/zog144-host-discover-eee9e574e8c139955da60b4b1bba4618c2912f48\n'
              'python3 -m installer --destdir="$DESTDIR" dist/*.whl\n']],
 'environment': {'PIP_NO_INDEX': '1', 'PYTHONNOUSERSITE': '1'}}
