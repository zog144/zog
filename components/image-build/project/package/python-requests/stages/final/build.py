# Data only; parsed with ast.literal_eval.
{'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/requests-2.34.2\n'
            "python3 - <<'ZOG_BUILD'\n"
            'import importlib,os,pathlib,sys,tomllib\n'
            "p=tomllib.loads(pathlib.Path('pyproject.toml').read_text())['build-system']\n"
            'from packaging.requirements import Requirement\n'
            'from importlib.metadata import version\n'
            'def check(items):\n'
            ' for text in items:\n'
            '  r=Requirement(text)\n'
            "  if r.marker and not r.marker.evaluate({'extra':''}): continue\n"
            "  assert version(r.name) in r.specifier, ('unsatisfied build "
            "requirement',text)\n"
            "check(p['requires'])\n"
            "for entry in reversed(p.get('backend-path',[])):\n"
            ' path=pathlib.Path(entry).resolve()\n'
            ' assert path.is_relative_to(pathlib.Path.cwd())\n'
            ' sys.path.insert(0,str(path))\n'
            "backend=importlib.import_module(p['build-backend'])\n"
            "extra=getattr(backend,'get_requires_for_build_wheel',lambda "
            'config: [])({})\n'
            'check(extra)\n'
            "pathlib.Path('dist').mkdir(exist_ok=True)\n"
            "print('ZOG_SOURCE_WHEEL',backend.build_wheel(str(pathlib.Path('dist').resolve()),{}),flush=True)\n"
            'ZOG_BUILD\n']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/requests-2.34.2\n'
           "python3 - <<'ZOG_TEST'\n"
           'import pathlib,zipfile,email\n'
           "wheels=list(pathlib.Path('dist').glob('*.whl'));assert "
           'len(wheels)==1\n'
           'with zipfile.ZipFile(wheels[0]) as z:\n'
           ' assert z.testzip() is None\n'
           ' names=z.namelist()\n'
           " assert all(not n.startswith('/') and '..' not in "
           'pathlib.PurePosixPath(n).parts for n in names)\n'
           ' m=email.message_from_bytes(z.read(next(n for n in names if '
           "n.count('/') == 1 and n.endswith('.dist-info/METADATA'))))\n"
           " assert m['Version']=='2.34.2'\n"
           " print('ZOG_WHEEL_VERIFIED',m['Name'],m['Version'])\n"
           'ZOG_TEST\n']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/requests-2.34.2\n'
              'python3 -m installer --destdir="$DESTDIR" dist/*.whl\n'
              'cd /\n'
              'PYTHONPATH="$DESTDIR/usr/lib/python3.15/site-packages" python3 '
              '-s -c \'import requests; print("ZOG_INSTALLED_IMPORT", '
              '\'"\'"\'requests\'"\'"\')\'\n']],
 'environment': {'PIP_NO_INDEX': '1', 'PYTHONNOUSERSITE': '1'}}
