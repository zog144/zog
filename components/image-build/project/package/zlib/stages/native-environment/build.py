# Data only; parsed with ast.literal_eval.
{'configure': [['/bin/bash', '-eu', '-c', 'cd upstream/zlib-1.3.2; ./configure --prefix=/usr']],
 'build': [['/bin/bash', '-eu', '-c', 'cd upstream/zlib-1.3.2; make -j4']],
 'install': [['/bin/bash',
              '-eu',
              '-c',
              'cd upstream/zlib-1.3.2; make DESTDIR="$DESTDIR" install; rm -f "$DESTDIR/usr/share/info/dir"; '
              'rm -f "$DESTDIR/usr/lib/libz.a"']]}
