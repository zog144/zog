# Data only; parsed with ast.literal_eval.
{'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/flit_core-3.12.0\n'
            "python3 - <<'ZOG_BUILD'\n"
            'import importlib,os,pathlib,sys,tomllib\n'
            "p=tomllib.loads(pathlib.Path('pyproject.toml').read_text())['build-system']\n"
            "for entry in reversed(p.get('backend-path',[])):\n"
            ' path=pathlib.Path(entry).resolve()\n'
            ' assert path.is_relative_to(pathlib.Path.cwd())\n'
            ' sys.path.insert(0,str(path))\n'
            "backend=importlib.import_module(p['build-backend'])\n"
            "extra=getattr(backend,'get_requires_for_build_wheel',lambda "
            'config: [])({})\n'
            'assert not extra, extra\n'
            "pathlib.Path('dist').mkdir(exist_ok=True)\n"
            "print('ZOG_SOURCE_WHEEL',backend.build_wheel(str(pathlib.Path('dist').resolve()),{}),flush=True)\n"
            'ZOG_BUILD\n']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/flit_core-3.12.0\n'
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
           " assert m['Version']=='3.12.0'\n"
           " print('ZOG_WHEEL_VERIFIED',m['Name'],m['Version'])\n"
           'ZOG_TEST\n']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/flit_core-3.12.0\n'
              'python3 bootstrap_install.py --install-root "$DESTDIR" '
              'dist/*.whl\n'
              'cd /\n'
              'PYTHONPATH="$DESTDIR/usr/lib/python3.15/site-packages" python3 '
              '-s -c \'import flit_core; print("ZOG_INSTALLED_IMPORT", '
              '\'"\'"\'flit-core\'"\'"\')\'\n']],
 'environment': {'PIP_NO_INDEX': '1', 'PYTHONNOUSERSITE': '1'}}
