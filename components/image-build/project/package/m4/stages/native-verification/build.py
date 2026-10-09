# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-c',
                'cd upstream/m4-1.4.21 && ./configure --prefix=/usr --disable-nls']],
 'build': [['make', '-C', 'upstream/m4-1.4.21', '-j4']],
 'test': [['/bin/bash',
           '-eu',
           '-c',
           'printf "eval(6*7)\\n" | upstream/m4-1.4.21/src/m4 | grep -x 42']],
 'install': [['/bin/bash',
              '-c',
              'set -eu; make -C upstream/m4-1.4.21/src install-binPROGRAMS; install -D -m644 '
              'upstream/m4-1.4.21/COPYING "$DESTDIR/usr/share/licenses/m4/COPYING"']]}
