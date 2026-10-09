# Data only; parsed with ast.literal_eval.
{'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/jinja-5ef70112a1ff19c05324ff889dd30405b1002044\n'
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
           'cd upstream/jinja-5ef70112a1ff19c05324ff889dd30405b1002044\n'
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
           ' from jinja2 import Environment, DictLoader, StrictUndefined, UndefinedError\n'
           ' from markupsafe import Markup\n'
           " loader=DictLoader({'unit':'[Unit]\\nDescription={{ description "
           "}}\\n[Service]\\nExecStart={{ executable }}\\n','base':'{% block content %}base{% "
           'endblock %}\',\'child\':\'{% extends "base" %}{% block content %}{{ value }}{% '
           "endblock %}'})\n"
           ' env=Environment(loader=loader,undefined=StrictUndefined)\n'
           " assert env.get_template('unit').render(description='Zog "
           "fixture',executable='/usr/bin/true') == '[Unit]\\nDescription=Zog "
           "fixture\\n[Service]\\nExecStart=/usr/bin/true'\n"
           " assert env.get_template('child').render(value='inherited') == 'inherited'\n"
           " assert Environment(autoescape=True).from_string('{{ value }}').render(value='<&>') == "
           "'&lt;&amp;&gt;'\n"
           " try:env.from_string('{{ missing }}').render()\n"
           ' except UndefinedError:pass\n'
           " else:raise AssertionError('undefined value accepted')\n"
           " print('ZOG_JINJA2_GENERATION_PASS')\n"
           'PYCHECK\n']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/jinja-5ef70112a1ff19c05324ff889dd30405b1002044\n'
              'python3 -m installer --destdir="$DESTDIR" dist/*.whl\n'
              'install -Dm644 LICENSE.txt '
              '"$DESTDIR/usr/share/licenses/python-jinja2/LICENSE.txt"']]}
