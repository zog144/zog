# Data only; parsed with ast.literal_eval.
{'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/meson-9874cbc93553d7bf424807afbfbcb1e22447cff8\n'
            "python3 - <<'PYBUILD'\n"
            'import pathlib,setuptools.build_meta\n'
            "pathlib.Path('dist').mkdir(exist_ok=True)\n"
            "print(setuptools.build_meta.build_wheel(str(pathlib.Path('dist').resolve())))\n"
            'PYBUILD\n']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/meson-9874cbc93553d7bf424807afbfbcb1e22447cff8\n'
           'python3 meson.py --version\n'
           'python3 -m compileall -q mesonbuild\n']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/meson-9874cbc93553d7bf424807afbfbcb1e22447cff8\n'
              'python3 -m installer --destdir="$DESTDIR" dist/*.whl\n'
              'install -Dm644 COPYING "$DESTDIR/usr/share/licenses/meson/COPYING"']]}
