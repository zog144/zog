# Data only; parsed with ast.literal_eval.
{'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/zog144-host-install-23f6d3dc3d2eab23ab11d7716cf5662ca6fea5d0\n'
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
           'cd upstream/zog144-host-install-23f6d3dc3d2eab23ab11d7716cf5662ca6fea5d0\n'
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
           ' exec("from importlib.metadata import version\\nimport host_install.state_contract, '
           "host_install.cli\\nassert version('host-install') == "
           '\'0.4.3\'\\nprint(\'ZOG_HOST_INSTALL_IMPORT_PASS\')\\n")\n'
           'ZOG_TEST\n']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/zog144-host-install-23f6d3dc3d2eab23ab11d7716cf5662ca6fea5d0\n'
              'python3 -m installer --destdir="$DESTDIR" dist/*.whl\n']],
 'environment': {'PIP_NO_INDEX': '1', 'PYTHONNOUSERSITE': '1'}}
