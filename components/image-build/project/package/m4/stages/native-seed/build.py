{'configure': [['/bin/bash',
                '-c',
                'cd upstream/m4-1.4.21 && ./configure --prefix=/usr '
                '--disable-nls']],
 'build': [['make', '-C', 'upstream/m4-1.4.21', '-j4']],
 'test': [['make', '-C', 'upstream/m4-1.4.21', '-j4', 'check']],
 'install': [['/bin/bash',
              '-c',
              'set -eu; make -C upstream/m4-1.4.21/src install-binPROGRAMS; '
              'install -D -m644 upstream/m4-1.4.21/COPYING '
              '"$DESTDIR/usr/share/licenses/m4/COPYING"']]}
