# Data only; parsed with ast.literal_eval.
{'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/setuptools-84.0.0\n'
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
           'cd upstream/setuptools-84.0.0\n'
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
           " assert m['Version']=='84.0.0'\n"
           " print('ZOG_WHEEL_VERIFIED',m['Name'],m['Version'])\n"
           'ZOG_TEST\n']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/setuptools-84.0.0\n'
              'python3 -m installer --destdir="$DESTDIR" dist/*.whl\n'
              'cd /\n'
              'PYTHONPATH="$DESTDIR/usr/lib/python3.15/site-packages" python3 '
              '-s -c \'import setuptools; print("ZOG_INSTALLED_IMPORT", '
              '\'"\'"\'setuptools\'"\'"\')\'\n']],
 'environment': {'PIP_NO_INDEX': '1', 'PYTHONNOUSERSITE': '1'},
 'prepare': [['/bin/bash',
              '-eu',
              '-c',
              "python3 - <<'ZOG_OMIT'\n"
              'import pathlib,hashlib\n'
              "for row in [{'path': 'setuptools-84.0.0/setuptools/cli-32.exe', "
              "'sha256': "
              "'32acc1bc543116cbe2cff10cb867772df2f254ff2634c870aef0b46c4b696fdb'}, "
              "{'path': 'setuptools-84.0.0/setuptools/cli-64.exe', 'sha256': "
              "'bbb3de5707629e6a60a0c238cd477b28f07f0066982fda953fa6fcec39073a4a'}, "
              "{'path': 'setuptools-84.0.0/setuptools/cli-arm64.exe', "
              "'sha256': "
              "'b9a7d08da880dfac8bcf548eba4b06fb59b6f09b17d33148a0f6618328926c61'}, "
              "{'path': 'setuptools-84.0.0/setuptools/cli.exe', 'sha256': "
              "'32acc1bc543116cbe2cff10cb867772df2f254ff2634c870aef0b46c4b696fdb'}, "
              "{'path': 'setuptools-84.0.0/setuptools/gui-32.exe', 'sha256': "
              "'85dae1e95d77845f2cb59bcac3d4afe74bbe4c91a9bcc5bf4a71cd43104dbe7c'}, "
              "{'path': 'setuptools-84.0.0/setuptools/gui-64.exe', 'sha256': "
              "'3471b6140eadc6412277dbbefe3fef8c345a0f1a59776086b80a3618c3a83e3b'}, "
              "{'path': 'setuptools-84.0.0/setuptools/gui-arm64.exe', "
              "'sha256': "
              "'e694f4743405c8b5926ff457db6fe7f1a12dec7c16a9c3864784d3f4e07ae097'}, "
              "{'path': 'setuptools-84.0.0/setuptools/gui.exe', 'sha256': "
              "'85dae1e95d77845f2cb59bcac3d4afe74bbe4c91a9bcc5bf4a71cd43104dbe7c'}]:\n"
              " p=pathlib.Path('upstream')/row['path']\n"
              ' assert '
              "hashlib.sha256(p.read_bytes()).hexdigest()==row['sha256']\n"
              ' p.unlink()\n'
              " print('ZOG_OMITTED_FOREIGN_LAUNCHER', row['path'])\n"
              'ZOG_OMIT\n']]}
