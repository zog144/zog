# Data only; parsed with ast.literal_eval.
{'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/markupsafe-4e111271b1494995708a9e878a10829b5e10c7ba\n'
            "CIBUILDWHEEL=1 python3 - <<'PYBUILD'\n"
            'import pathlib,importlib,tomllib\n'
            'from packaging.requirements import Requirement\n'
            'from importlib.metadata import version\n'
            "p=tomllib.loads(pathlib.Path('pyproject.toml').read_text())\n"
            "for text in p['build-system']['requires']+p['project'].get('dependencies',[]):\n"
            ' r=Requirement(text)\n'
            ' if r.marker is None or r.marker.evaluate():assert '
            'r.specifier.contains(version(r.name),prereleases=True),text\n'
            "backend=importlib.import_module(p['build-system']['build-backend'])\n"
            "pathlib.Path('dist').mkdir(exist_ok=True)\n"
            "print(backend.build_wheel(str(pathlib.Path('dist').resolve())))\n"
            'PYBUILD\n']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/markupsafe-4e111271b1494995708a9e878a10829b5e10c7ba\n'
           "python3 - <<'PYCHECK'\n"
           'import pathlib,zipfile,tempfile,sys\n'
           "wheels=list(pathlib.Path('dist').glob('*.whl')); assert len(wheels)==1\n"
           'with tempfile.TemporaryDirectory() as d:\n'
           ' with zipfile.ZipFile(wheels[0]) as z:\n'
           '  assert z.testzip() is None\n'
           "  assert all(not p.startswith('/') and '..' not in pathlib.PurePosixPath(p).parts for "
           'p in z.namelist())\n'
           '  z.extractall(d)\n'
           ' sys.path.insert(0,d)\n'
           ' from markupsafe import Markup, escape\n'
           ' import markupsafe._speedups as native\n'
           " assert native.__file__.endswith('.so'), native.__file__\n"
           " assert str(escape('<&>')) == '&lt;&amp;&gt;'\n"
           " assert str(Markup('<b>%s</b>') % '<unsafe>') == '<b>&lt;unsafe&gt;</b>'\n"
           " assert Markup('&lt;b&gt;').unescape() == '<b>'\n"
           " print('ZOG_MARKUPSAFE_NATIVE_PASS')\n"
           'PYCHECK\n']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/markupsafe-4e111271b1494995708a9e878a10829b5e10c7ba\n'
              'python3 -m installer --destdir="$DESTDIR" dist/*.whl\n'
              'install -Dm644 LICENSE.txt '
              '"$DESTDIR/usr/share/licenses/python-markupsafe/LICENSE.txt"']]}
