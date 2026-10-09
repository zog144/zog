# Data only; parsed with ast.literal_eval.
{'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/installer-1.0.1\n'
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
           'cd upstream/installer-1.0.1\n'
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
           " assert m['Version']=='1.0.1'\n"
           " print('ZOG_WHEEL_VERIFIED',m['Name'],m['Version'])\n"
           'ZOG_TEST\n']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/installer-1.0.1\n'
              'PYTHONPATH=src python3 -m installer --destdir="$DESTDIR" '
              'dist/*.whl\n'
              'cd /\n'
              'PYTHONPATH="$DESTDIR/usr/lib/python3.15/site-packages" python3 '
              '-s -c \'import installer; print("ZOG_INSTALLED_IMPORT", '
              '\'"\'"\'installer\'"\'"\')\'\n']],
 'environment': {'PIP_NO_INDEX': '1', 'PYTHONNOUSERSITE': '1'},
 'prepare': [['/bin/bash',
              '-eu',
              '-c',
              "python3 - <<'ZOG_OMIT'\n"
              'import pathlib,hashlib\n'
              "for row in [{'path': "
              "'installer-1.0.1/src/installer/_scripts/t32.exe', 'sha256': "
              "'6b4195e640a85ac32eb6f9628822a622057df1e459df7c17a12f97aeabc9415b'}, "
              "{'path': 'installer-1.0.1/src/installer/_scripts/t64-arm.exe', "
              "'sha256': "
              "'ebc4c06b7d95e74e315419ee7e88e1d0f71e9e9477538c00a93a9ff8c66a6cfc'}, "
              "{'path': 'installer-1.0.1/src/installer/_scripts/t64.exe', "
              "'sha256': "
              "'81a618f21cb87db9076134e70388b6e9cb7c2106739011b6a51772d22cae06b7'}, "
              "{'path': 'installer-1.0.1/src/installer/_scripts/t_arm.exe', "
              "'sha256': "
              "'62aee48069f0715f96da0dbe35eab7868d5cb149f62133141ab0e126d62b9cfe'}, "
              "{'path': 'installer-1.0.1/src/installer/_scripts/w32.exe', "
              "'sha256': "
              "'47872cc77f8e18cf642f868f23340a468e537e64521d9a3a416c8b84384d064b'}, "
              "{'path': 'installer-1.0.1/src/installer/_scripts/w64-arm.exe', "
              "'sha256': "
              "'c5dc9884a8f458371550e09bd396e5418bf375820a31b9899f6499bf391c7b2e'}, "
              "{'path': 'installer-1.0.1/src/installer/_scripts/w64.exe', "
              "'sha256': "
              "'7a319ffaba23a017d7b1e18ba726ba6c54c53d6446db55f92af53c279894f8ad'}, "
              "{'path': 'installer-1.0.1/src/installer/_scripts/w_arm.exe', "
              "'sha256': "
              "'091feafac1542754885b1b2bc57bf8a66e89351e6aa2c05ebf053fd7b66a2aba'}]:\n"
              " p=pathlib.Path('upstream')/row['path']\n"
              ' assert '
              "hashlib.sha256(p.read_bytes()).hexdigest()==row['sha256']\n"
              ' p.unlink()\n'
              " print('ZOG_OMITTED_FOREIGN_LAUNCHER', row['path'])\n"
              'ZOG_OMIT\n']]}
