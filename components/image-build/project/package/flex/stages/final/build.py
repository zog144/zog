# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash',
                '-eu',
                '-o',
                'pipefail',
                '-c',
                'for tool in gcc g++ make m4 bison perl; do command -v "$tool"; done; cd '
                'upstream/flex-2.6.4; ./configure --prefix=/usr --disable-static '
                '--docdir=/usr/share/doc/flex-2.6.4']],
 'build': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'make -C upstream/flex-2.6.4 -j8']],
 'test': [['/bin/bash', '-eu', '-o', 'pipefail', '-c', 'make -C upstream/flex-2.6.4 check']],
 'install': [['/bin/bash',
              '-eu',
              '-o',
              'pipefail',
              '-c',
              'make -C upstream/flex-2.6.4 DESTDIR="$DESTDIR" install; ln -sf flex '
              '"$DESTDIR/usr/bin/lex"; ln -sf flex.1 "$DESTDIR/usr/share/man/man1/lex.1"; rm -f '
              '"$DESTDIR/usr/share/info/dir"']]}
