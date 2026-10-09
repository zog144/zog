# Data only; parsed with ast.literal_eval.
{'build': [['/bin/bash',
            '-eu',
            '-o',
            'pipefail',
            '-c',
            'cd upstream/ninja-4e4df1e567eb3c1475a51af261cba2bfff60b4be\n'
            'python3 configure.py --bootstrap\n']],
 'test': [['/bin/bash',
           '-eu',
           '-o',
           'pipefail',
           '-c',
           'cd upstream/ninja-4e4df1e567eb3c1475a51af261cba2bfff60b4be\n'
           'python3 misc/ninja_syntax_test.py\n'
           './ninja --version\n']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'cd upstream/ninja-4e4df1e567eb3c1475a51af261cba2bfff60b4be\n'
              'install -Dm755 ninja "$DESTDIR/usr/bin/ninja"\n'
              'install -Dm644 COPYING "$DESTDIR/usr/share/licenses/ninja/COPYING"']]}
